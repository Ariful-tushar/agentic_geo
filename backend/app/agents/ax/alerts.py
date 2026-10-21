"""Ax step 9: alerts when an answer changed since the previous completed live run.

Only live runs make alerts; the comparison is per engine and question. Summaries are plain text
built by code (no AI). A run that has no earlier completed live run makes no alerts.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ax.mentions import DONE_KEY
from app.agents.ax.nodes import AxDeps, AxState, Context, load_context
from app.db.models import Alert, Answer, Mention, Question, Run, Score

WARNING, INFO = "warning", "info"


@dataclass
class Snapshot:
    """What one answer looked like: its score, and (generic answers) who was named where."""

    answer_id: uuid.UUID
    verdict: str | None = None
    score: float | None = None
    mentions_done: bool = False
    company_rank: int | None = None
    competitor_ranks: tuple[int, ...] = ()

    def competitor_ahead(self) -> bool:
        return self.company_rank is not None and any(
            r < self.company_rank for r in self.competitor_ranks
        )


def decide(kind: str, before: Snapshot, after: Snapshot) -> str | None:
    """The alert kind for a change between two snapshots of the same engine and question."""
    if kind == "fact":
        if before.score is None or after.score is None or before.score == after.score:
            return None
        return "score_drop" if after.score < before.score else "score_improved"
    if not (before.mentions_done and after.mentions_done):
        return None
    if before.company_rank is not None and after.company_rank is None:
        return "company_dropped"
    if (
        before.company_rank is not None
        and after.company_rank is not None
        and after.competitor_ahead()
        and not before.competitor_ahead()
    ):
        return "competitor_overtook"
    return None


def summary(
    kind: str, engine: str, question: Question, before: Snapshot, after: Snapshot, company: str
) -> str:
    where = f"{engine}, {question.code}"
    if kind in ("score_drop", "score_improved"):
        word = "got worse" if kind == "score_drop" else "got better"
        return f"{where}: the answer {word} ({before.verdict} -> {after.verdict}). {question.text}"
    if kind == "company_dropped":
        return f"{where}: {company} was named before but is not named now. {question.text}"
    return f"{where}: a competitor is now named before {company}. {question.text}"


async def previous_run(session: AsyncSession, state: AxState) -> Run | None:
    return await session.scalar(
        select(Run)
        .where(
            Run.company_id == state["company_id"],
            Run.kind == "ax",
            Run.mode == "live",
            Run.status == "completed",
            Run.run_date < state["run_date"],
        )
        .order_by(Run.run_date.desc())
        .limit(1)
    )


async def snapshots(session: AsyncSession, run: Run) -> dict[tuple[str, uuid.UUID], Snapshot]:
    """Snapshots of the good answers of a run, keyed by (engine, question id)."""
    answers = (
        await session.scalars(
            select(Answer).where(
                Answer.run_id == run.id, Answer.error.is_(None), Answer.text.is_not(None)
            )
        )
    ).all()
    scores = {
        s.answer_id: s
        for s in (
            await session.scalars(select(Score).where(Score.answer_id.in_([a.id for a in answers])))
        ).all()
    }
    mentions: dict[uuid.UUID, list[Mention]] = {}
    for m in (
        await session.scalars(select(Mention).where(Mention.answer_id.in_([a.id for a in answers])))
    ).all():
        mentions.setdefault(m.answer_id, []).append(m)
    done = set((run.details or {}).get(DONE_KEY, []))

    result = {}
    for a in answers:
        snap = Snapshot(answer_id=a.id, mentions_done=str(a.id) in done)
        if a.id in scores:
            snap.verdict, snap.score = scores[a.id].verdict, float(scores[a.id].score)
        rows = mentions.get(a.id, [])
        snap.company_rank = next((m.rank for m in rows if m.brand_type == "company"), None)
        snap.competitor_ranks = tuple(m.rank for m in rows if m.brand_type == "competitor")
        result[(a.engine, a.question_id)] = snap
    return result


async def alerts(state: AxState, deps: AxDeps) -> dict[str, Any]:
    if state["mode"] != "live":  # trial runs never make alerts
        return {}
    created = 0
    async with deps.sessionmaker() as session:
        before_run = await previous_run(session, state)
        if before_run is None:
            return {}
        ctx: Context = await load_context(session, state["company_id"], state["mode"])
        current = await session.get(Run, uuid.UUID(state["run_id"]))
        assert current is not None
        before_snaps, after_snaps = (
            await snapshots(session, before_run),
            await snapshots(session, current),
        )
        questions = {q.id: q for q in ctx.questions}
        for key, after in after_snaps.items():
            before = before_snaps.get(key)
            question = questions.get(key[1])
            if before is None or question is None:
                continue
            kind = decide(question.kind, before, after)
            if kind is None:
                continue
            stmt = (
                insert(Alert)
                .values(
                    company_id=state["company_id"],
                    run_date=state["run_date"],
                    kind=kind,
                    severity=INFO if kind == "score_improved" else WARNING,
                    engine=key[0],
                    question_id=question.id,
                    before_answer_id=before.answer_id,
                    after_answer_id=after.answer_id,
                    summary=summary(kind, key[0], question, before, after, ctx.company_name),
                )
                .on_conflict_do_nothing()
                .returning(Alert.id)
            )
            created += len((await session.execute(stmt)).all())  # only rows really inserted
        await session.commit()
    return {"work": created}
