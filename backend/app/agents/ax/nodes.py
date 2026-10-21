"""Ax graph nodes, part 1 (SPEC 8.2 steps 1-5 and 10; steps 6-9 live in why/mentions/alerts).

Every node reads what is already stored for today's run and only does the missing work, so the
whole run can be repeated or resumed. Each answer or score is committed as soon as it exists.
"""

import asyncio
import logging
import operator
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Annotated, Any, TypedDict
from urllib.parse import urlparse

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.ax import judge as judging
from app.db.models import (
    Alert,
    Answer,
    Citation,
    Company,
    Competitor,
    CompetitorEvent,
    DailyAccuracy,
    Mention,
    Question,
    Run,
    Score,
    WhyFinding,
)
from app.kb.retriever import NOT_FOUND, KnowledgeBaseEmpty, rag_answer
from app.llm.engines import Engine
from app.llm.internal import InternalAIError
from app.llm.limits import DailyStop
from app.schemas.agents import Citation as CitationIn

log = logging.getLogger(__name__)

DEV_FACT_QUESTIONS = 4
DEV_GENERIC_QUESTIONS = 2
MAX_CONSECUTIVE_ERRORS = 3
RAG = "rag"


class AxState(TypedDict, total=False):
    company_id: str
    mode: str
    trigger: str
    run_id: str
    run_date: date
    stop: bool
    message: str
    status: str
    was_complete: bool
    skipped_engines: Annotated[list[str], operator.add]
    warnings: Annotated[list[str], operator.add]
    work: Annotated[int, operator.add]  # new rows/answers created by the nodes in this invocation


@dataclass
class AxDeps:
    sessionmaker: async_sessionmaker[AsyncSession]
    engine: AsyncEngine
    engines: list[Engine]
    llm: Callable[..., Any]
    embeddings: Embeddings
    today: Callable[[], date]
    fetcher: Any  # PoliteFetcher-like: `await fetcher.fetch(session, url)`
    wikipedia: Callable[[str], Awaitable[str | None]]  # page title -> plain text
    kb_search: Callable[[str, str], Awaitable[list[Document]]]  # (company_id, query) -> chunks


# ---- helpers ---------------------------------------------------------------------------------


def host_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def _matches(host: str, domains: list[str]) -> bool:
    return any(
        host == d.lower().removeprefix("www.") or host.endswith("." + d.lower()) for d in domains
    )


def classify_owner(
    url: str, company_domains: list[str], competitors: list[tuple[uuid.UUID, list[str]]]
) -> tuple[str, uuid.UUID | None]:
    """Who owns the cited page: the company, a competitor, or a third party."""
    host = host_of(url)
    if _matches(host, company_domains):
        return "company", None
    for competitor_id, domains in competitors:
        if _matches(host, domains):
            return "competitor", competitor_id
    return "third_party", None


@dataclass
class Brand:
    """A company or competitor whose name we look for in answers."""

    name: str
    aliases: list[str]
    type: str  # company | competitor
    competitor_id: uuid.UUID | None = None

    @property
    def names(self) -> list[str]:
        return [self.name, *self.aliases]


@dataclass
class Context:
    company_domains: list[str]
    competitors: list[tuple[uuid.UUID, list[str]]]
    facts: list[Question]
    generics: list[Question]
    company_name: str = ""
    wikipedia_title: str | None = None
    brands: list[Brand] = field(default_factory=list)

    @property
    def questions(self) -> list[Question]:
        return [*self.facts, *self.generics]


async def load_context(session: AsyncSession, company_id: str, mode: str) -> Context:
    company = await session.get(Company, company_id)
    if company is None:
        raise ValueError(f"unknown company '{company_id}'")
    competitors = (
        await session.scalars(
            select(Competitor).where(Competitor.company_id == company_id, Competitor.active)
        )
    ).all()
    questions = (
        await session.scalars(
            select(Question).where(Question.company_id == company_id).order_by(Question.code)
        )
    ).all()
    facts = [q for q in questions if q.kind == "fact"]
    generics = [q for q in questions if q.kind == "generic"]
    if mode == "dev":
        facts, generics = facts[:DEV_FACT_QUESTIONS], generics[:DEV_GENERIC_QUESTIONS]
    return Context(
        company_domains=list(company.domains),
        competitors=[(c.id, list(c.domains)) for c in competitors],
        facts=facts,
        generics=generics,
        company_name=company.name,
        wikipedia_title=company.wikipedia_title,
        brands=[
            Brand(company.name, list(company.aliases), "company"),
            *(Brand(c.name, list(c.aliases), "competitor", c.id) for c in competitors),
        ],
    )


async def get_run(session: AsyncSession, run_id: str) -> Run:
    run = await session.get(Run, uuid.UUID(run_id))
    assert run is not None
    return run


async def merge_details(session: AsyncSession, run_id: str, **values: Any) -> None:
    run = await get_run(session, run_id)
    run.details = {**(run.details or {}), **values}
    await session.commit()


async def good_answers(session: AsyncSession, run_id: str, engine: str) -> set[uuid.UUID]:
    """Question ids already answered today without an error."""
    rows = await session.scalars(
        select(Answer.question_id).where(
            Answer.run_id == uuid.UUID(run_id),
            Answer.engine == engine,
            Answer.error.is_(None),
            Answer.text.is_not(None),
        )
    )
    return set(rows.all())


async def store_answer(
    session: AsyncSession,
    state: AxState,
    ctx: Context,
    question: Question,
    engine_id: str,
    *,
    text: str | None,
    raw_json: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    error: str | None = None,
    citations: list[CitationIn] | None = None,
) -> None:
    """Insert or update the answer for (run, question, engine); replace its citations."""
    run_id = uuid.UUID(state["run_id"])
    row = await session.scalar(
        select(Answer).where(
            Answer.run_id == run_id, Answer.question_id == question.id, Answer.engine == engine_id
        )
    )
    if row is None:
        row = Answer(
            run_id=run_id, company_id=state["company_id"], question_id=question.id, engine=engine_id
        )
        session.add(row)
    else:  # a retried answer: forget the old score and citations
        await session.execute(delete(Score).where(Score.answer_id == row.id))
        await session.execute(delete(Citation).where(Citation.answer_id == row.id))
    row.text, row.raw_json, row.latency_ms, row.error = text, raw_json, latency_ms, error
    row.asked_at = datetime.now(UTC)
    await session.flush()
    seen: set[str] = set()
    for cite in citations or []:
        if cite.url in seen:
            continue
        seen.add(cite.url)
        owner, competitor_id = classify_owner(cite.url, ctx.company_domains, ctx.competitors)
        session.add(
            Citation(
                answer_id=row.id,
                url=cite.url,
                title=cite.title,
                domain=host_of(cite.url),
                owner=owner,
                competitor_id=competitor_id,
            )
        )
    await session.commit()


# ---- node 1: start ---------------------------------------------------------------------------


async def start(state: AxState, deps: AxDeps) -> dict[str, Any]:
    async with deps.sessionmaker() as session:
        company = await session.get(Company, state["company_id"])
        if company is None:
            raise ValueError(f"unknown company '{state['company_id']}'")
        run_date = deps.today()
        run = await session.scalar(
            select(Run).where(
                Run.company_id == company.id,
                Run.kind == "ax",
                Run.run_date == run_date,
                Run.mode == state["mode"],  # a dev run never counts as today's live run
            )
        )
        if run is None:
            run = Run(
                company_id=company.id,
                kind="ax",
                run_date=run_date,
                mode=state["mode"],
                details={},
            )
            session.add(run)
        was_complete = run.status == "completed"
        if not company.monitoring_enabled and state["trigger"] == "schedule":
            if not was_complete:
                run.trigger, run.status, run.finished_at = "schedule", "skipped", datetime.now(UTC)
            await session.commit()
            return {
                "run_id": str(run.id),
                "run_date": run_date,
                "stop": True,
                "status": run.status,
                "message": "Today's run is already complete"
                if was_complete
                else "Monitoring is switched off for this company",
            }
        if not was_complete:  # a repeat of a finished run keeps its trigger and finish time
            run.trigger, run.finished_at = state["trigger"], None
        run.status = "running"
        await session.commit()
        return {
            "run_id": str(run.id),
            "run_date": run_date,
            "stop": False,
            "was_complete": was_complete,
        }


# ---- node 2: ask_engines ---------------------------------------------------------------------


async def _ask_one_engine(
    deps: AxDeps, state: AxState, ctx: Context, engine: Engine
) -> tuple[list[str], bool, int]:
    """Ask every missing question. Returns (warnings, engine_skipped, answers_stored)."""
    async with deps.sessionmaker() as session:
        done = await good_answers(session, state["run_id"], engine.id)
        if all(q.id in done for q in ctx.questions):
            return [], False, 0  # nothing to ask: no key needed, no call made
        if not engine.has_key():
            return [f"{engine.id}: skipped, no API key"], True, 0
        errors = consecutive = stored = 0
        for question in ctx.questions:
            if question.id in done:
                continue
            try:
                answer = await engine.ask(question.text)
            except DailyStop as exc:
                return [f"{engine.id}: stopped, {exc}"], True, stored
            except Exception as exc:
                errors += 1
                stored += 1
                consecutive += 1
                message = f"{type(exc).__name__}: {exc}"[:300]
                await store_answer(
                    session, state, ctx, question, engine.id, text=None, error=message
                )
                if consecutive >= MAX_CONSECUTIVE_ERRORS:
                    return (
                        [f"{engine.id}: stopped after {consecutive} errors in a row ({message})"],
                        True,
                        stored,
                    )
                continue
            consecutive = 0
            stored += 1
            await store_answer(
                session,
                state,
                ctx,
                question,
                engine.id,
                text=answer.text,
                raw_json={**answer.raw_json, "model": answer.model},
                latency_ms=answer.latency_ms,
                citations=answer.citations,
            )
    return ([f"{engine.id}: {errors} question(s) failed"] if errors else []), False, stored


async def ask_engines(state: AxState, deps: AxDeps) -> dict[str, Any]:
    async with deps.sessionmaker() as session:
        ctx = await load_context(session, state["company_id"], state["mode"])
    results = await asyncio.gather(*(_ask_one_engine(deps, state, ctx, e) for e in deps.engines))
    warnings = [w for found, _, _ in results for w in found]
    skipped = [
        e.id for e, (_, was_skipped, _) in zip(deps.engines, results, strict=True) if was_skipped
    ]
    return {"warnings": warnings, "skipped_engines": skipped, "work": sum(r[2] for r in results)}


# ---- node 3: ask_rag -------------------------------------------------------------------------


async def ask_rag(state: AxState, deps: AxDeps) -> dict[str, Any]:
    async with deps.sessionmaker() as session:
        ctx = await load_context(session, state["company_id"], state["mode"])
        done = await good_answers(session, state["run_id"], RAG)
        warnings: list[str] = []
        errors = stored = 0
        for question in ctx.facts:
            if question.id in done:
                continue
            try:
                result = await rag_answer(
                    deps.engine,
                    state["company_id"],
                    question.text,
                    mode=state["mode"],  # type: ignore[arg-type]
                    embeddings=deps.embeddings,
                    llm=deps.llm,
                )
            except KnowledgeBaseEmpty:
                return {
                    "warnings": ["rag: skipped, the knowledge base is empty (run onboard)"],
                    "skipped_engines": [RAG],
                    "work": stored,
                }
            except (DailyStop, InternalAIError) as exc:
                return {
                    "warnings": [f"rag: stopped, {exc}"],
                    "skipped_engines": [RAG],
                    "work": stored,
                }
            except Exception as exc:
                errors += 1
                stored += 1
                message = f"{type(exc).__name__}: {exc}"[:300]
                await store_answer(session, state, ctx, question, RAG, text=None, error=message)
                continue
            await store_answer(
                session,
                state,
                ctx,
                question,
                RAG,
                text=result.answer,
                raw_json={
                    **result.raw_json,
                    "found": result.found,
                    "quotes": [q.model_dump() for q in result.quotes],
                },
                citations=[CitationIn(url=u) for u in result.source_urls],
            )
            stored += 1
        if errors:
            warnings.append(f"rag: {errors} question(s) failed")
    return {"warnings": warnings, "work": stored}


# ---- node 4: judge ---------------------------------------------------------------------------


async def judge(state: AxState, deps: AxDeps) -> dict[str, Any]:
    warnings: list[str] = []
    scored = 0
    async with deps.sessionmaker() as session:
        rows = (
            await session.execute(
                select(Answer, Question)
                .join(Question, Question.id == Answer.question_id)
                .outerjoin(Score, Score.answer_id == Answer.id)
                .where(
                    Answer.run_id == uuid.UUID(state["run_id"]),
                    Question.kind == "fact",
                    Answer.error.is_(None),
                    Answer.text.is_not(None),
                    Score.id.is_(None),
                )
                .order_by(Answer.engine, Question.code)
            )
        ).all()
        by_engine: dict[str, list[tuple[Answer, Question]]] = {}
        for answer, question in rows:
            by_engine.setdefault(answer.engine, []).append((answer, question))

        for engine_id, pairs in by_engine.items():
            verdicts: dict[str, judging.Verdict] = {}
            to_judge: list[judging.JudgeInput] = []
            for answer, question in pairs:
                if engine_id == RAG and answer.text == NOT_FOUND:
                    verdicts[question.code] = judging.no_answer(
                        "RAG found no verified answer in the company's pages."
                    )
                elif not (answer.text or "").strip():
                    verdicts[question.code] = judging.no_answer("The answer was empty.")
                else:
                    to_judge.append(
                        judging.JudgeInput(
                            code=question.code,
                            question=question.text,
                            expected_answer=question.expected_answer or "",
                            answer=answer.text or "",
                            expected_value=float(question.expected_value)
                            if question.expected_value is not None
                            else None,
                            tolerance=float(question.tolerance)
                            if question.tolerance is not None
                            else None,
                            unit=question.unit,
                        )
                    )
            if to_judge:
                try:
                    verdicts.update(await judging.judge_engine(to_judge, deps.llm, state["mode"]))  # type: ignore[arg-type]
                except (DailyStop, InternalAIError) as exc:
                    warnings.append(f"judge: {engine_id} not scored yet, {exc}")
            for answer, question in pairs:
                verdict = verdicts.get(question.code)
                if verdict is None:
                    continue
                scored += 1
                session.add(
                    Score(
                        answer_id=answer.id,
                        verdict=verdict.verdict,
                        score=verdict.score,
                        reason=verdict.reason,
                        quote=verdict.quote,
                        quote_verified=verdict.quote_verified,
                        method=verdict.method,
                    )
                )
            await session.commit()
    return {"warnings": warnings, "work": scored}


# ---- node 5: daily_accuracy ------------------------------------------------------------------


async def daily_accuracy(state: AxState, deps: AxDeps) -> dict[str, Any]:
    async with deps.sessionmaker() as session:
        rows = (
            await session.execute(
                select(Answer.engine, Score.verdict, Score.score)
                .join(Score, Score.answer_id == Answer.id)
                .join(Question, Question.id == Answer.question_id)
                .where(Answer.run_id == uuid.UUID(state["run_id"]), Question.kind == "fact")
            )
        ).all()
        per_engine: dict[str, list[tuple[str, float]]] = {}
        for engine, verdict, score in rows:
            per_engine.setdefault(engine, []).append((verdict, float(score)))
        for engine, items in per_engine.items():
            counts = judging.count_verdicts([v for v, _ in items])
            values = {
                "company_id": state["company_id"],
                "run_id": uuid.UUID(state["run_id"]),
                "run_date": state["run_date"],
                "engine": engine,
                "mode": state["mode"],
                "accuracy": judging.accuracy([s for _, s in items]),
                "n_questions": len(items),
                "n_correct": counts["correct"],
                "n_partial": counts["partial"],
                "n_wrong": counts["wrong"],
                "n_no_answer": counts["no_answer"],
            }
            key = ("company_id", "run_date", "engine", "mode")
            stmt = insert(DailyAccuracy).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=list(key),
                set_={k: v for k, v in values.items() if k not in key},
            )
            await session.execute(stmt)
        await session.commit()
    return {}


# ---- node 10: finish -------------------------------------------------------------------------


async def _step_counts(session: AsyncSession, run_id: uuid.UUID) -> dict[str, Any]:
    """What steps 6-9 stored for this run, for the run summary."""
    answer_ids = select(Answer.id).where(Answer.run_id == run_id)
    why = await session.execute(
        select(WhyFinding.source_type, func.count())
        .where(WhyFinding.answer_id.in_(answer_ids))
        .group_by(WhyFinding.source_type)
    )
    events = await session.execute(
        select(CompetitorEvent.kind, func.count())
        .where(CompetitorEvent.answer_id.in_(answer_ids))
        .group_by(CompetitorEvent.kind)
    )
    alerts = await session.execute(
        select(Alert.kind, func.count())
        .where(Alert.after_answer_id.in_(answer_ids))
        .group_by(Alert.kind)
    )
    mentions = await session.scalar(
        select(func.count()).select_from(Mention).where(Mention.answer_id.in_(answer_ids))
    )
    return {
        "why_findings": dict(why.all()),
        "mentions": mentions,
        "competitor_events": dict(events.all()),
        "alerts": dict(alerts.all()),
    }


async def finish(state: AxState, deps: AxDeps) -> dict[str, Any]:
    run_id = uuid.UUID(state["run_id"])
    warnings = state.get("warnings", [])
    async with deps.sessionmaker() as session:
        run = await get_run(session, state["run_id"])
        if state.get("was_complete") and not state.get("work") and not warnings:
            run.status = "completed"  # nothing new was added: leave the finished run untouched
            await session.commit()
            return {"status": "completed", "message": "Today's run is already complete"}

        ctx = await load_context(session, state["company_id"], state["mode"])
        answers = (await session.scalars(select(Answer).where(Answer.run_id == run_id))).all()
        good = [a for a in answers if a.error is None and a.text is not None]
        expected = len(deps.engines) * len(ctx.questions) + len(ctx.facts)
        scored = set(
            (
                await session.scalars(
                    select(Score.answer_id).join(Answer).where(Answer.run_id == run_id)
                )
            ).all()
        )
        fact_ids = {q.id for q in ctx.facts}
        unscored = [a for a in good if a.question_id in fact_ids and a.id not in scored]
        errors = [a for a in answers if a.error is not None]
        complete = len(good) >= expected and not unscored and not warnings
        status = "completed" if complete else "partial"
        accuracy = {
            row.engine: round(float(row.accuracy), 3)
            for row in (
                await session.scalars(select(DailyAccuracy).where(DailyAccuracy.run_id == run_id))
            ).all()
        }
        run.status, run.finished_at = status, datetime.now(UTC)
        run.details = {
            **(run.details or {}),
            "mode": state["mode"],
            "questions": {"fact": len(ctx.facts), "generic": len(ctx.generics)},
            "answers_ok": len(good),
            "answers_expected": expected,
            "answers_with_error": len(errors),
            "unscored": len(unscored),
            "skipped_engines": sorted(set(state.get("skipped_engines", []))),
            "warnings": warnings,
            "accuracy": accuracy,
            **await _step_counts(session, run_id),
        }
        await session.commit()
    return {"status": status}
