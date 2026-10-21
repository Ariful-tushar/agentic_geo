"""Read endpoints (SPEC 9). Public; they only ever return live data, never dev trial runs."""

import uuid
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import optional_admin
from app.api.deps import get_today
from app.db import repo
from app.db.models import Company, Question, Run
from app.db.session import get_session
from app.llm.engines import load_engines
from app.schemas.api import (
    AlertOut,
    AnswerDetail,
    CitationOut,
    CompanyDetail,
    CompanyListItem,
    CompetitorOut,
    DetailCell,
    DetailRow,
    DetailsOut,
    EmailLogOut,
    EngineOut,
    PreviousAnswer,
    QuestionOut,
    RunOut,
    ScoreOut,
    SourceOut,
    TodayItem,
    TrendPoint,
    WhyOut,
)

router = APIRouter(prefix="/api")

Session = Annotated[AsyncSession, Depends(get_session)]
Today = Annotated[date, Depends(get_today)]

RAG_ENGINE = EngineOut(
    id="rag",
    label="Our RAG on the company's own pages",
    web_search=False,
    enabled=True,
)
RUN_SUMMARY_KEYS = (
    "answers_ok",
    "answers_expected",
    "answers_with_error",
    "unscored",
    "skipped_engines",
    "warnings",
    "accuracy",
)
MAX_DETAIL_DAYS = 366


# ---- converters ------------------------------------------------------------------------------


def run_out(run: Run) -> RunOut:
    details = run.details or {}
    return RunOut(
        id=run.id,
        kind=run.kind,
        mode=run.mode,
        status=run.status,
        trigger=run.trigger,
        run_date=run.run_date,
        started_at=run.started_at,
        finished_at=run.finished_at,
        summary={k: details[k] for k in RUN_SUMMARY_KEYS if k in details},
    )


def question_out(q: Question) -> QuestionOut:
    return QuestionOut(
        id=q.id,
        code=q.code,
        kind=q.kind,
        text=q.text,
        expected_answer=q.expected_answer,
        expected_value=None if q.expected_value is None else float(q.expected_value),
        tolerance=None if q.tolerance is None else float(q.tolerance),
        unit=q.unit,
        expected_source_url=q.expected_source_url,
    )


async def company_or_404(session: AsyncSession, company_id: str) -> Company:
    company = await session.get(Company, company_id)
    if company is None:
        raise HTTPException(404, f"Unknown company '{company_id}'")
    return company


def known_engine_ids() -> set[str]:
    return {e.id for e in load_engines()} | {"rag"}


# ---- endpoints -------------------------------------------------------------------------------


@router.get("/engines", response_model=list[EngineOut], tags=["engines"])
async def engines() -> list[EngineOut]:
    """The tested engines (from config/engines.yaml) plus the pseudo-engine `rag`."""
    tested = [
        EngineOut(id=e.id, label=e.config.label, web_search=e.config.web_search, enabled=e.enabled)
        for e in load_engines()
    ]
    return [*tested, RAG_ENGINE]


@router.get("/companies", response_model=list[CompanyListItem], tags=["companies"])
async def companies(session: Session) -> list[CompanyListItem]:
    return [
        CompanyListItem(
            id=c.id,
            name=c.name,
            onboarding_status=c.onboarding_status,
            monitoring_enabled=c.monitoring_enabled,
            last_run=run_out(run) if run else None,
        )
        for c, run in await repo.list_companies(session)
    ]


@router.get("/companies/{company_id}", response_model=CompanyDetail, tags=["companies"])
async def company_detail(
    company_id: str, session: Session, is_admin: Annotated[bool, Depends(optional_admin)]
) -> CompanyDetail:
    parts = await repo.get_company_parts(session, company_id)
    if parts is None:
        raise HTTPException(404, f"Unknown company '{company_id}'")
    company, competitors, questions, sources, last_run = parts
    return CompanyDetail(
        id=company.id,
        name=company.name,
        aliases=company.aliases,
        domains=company.domains,
        wikipedia_title=company.wikipedia_title,
        contact_email_count=len(company.contact_emails),
        contact_emails=list(company.contact_emails) if is_admin else None,
        faq_source_urls=company.faq_source_urls,
        monitoring_enabled=company.monitoring_enabled,
        emails_enabled=company.emails_enabled,
        onboarding_status=company.onboarding_status,
        onboarding_error=company.onboarding_error,
        competitors=[
            CompetitorOut(
                id=c.id, name=c.name, aliases=c.aliases, domains=c.domains, active=c.active
            )
            for c in competitors
        ],
        questions=[question_out(q) for q in questions],
        knowledge_sources=[
            SourceOut(url=s.url, status=s.status, last_built_at=s.last_built_at, active=s.active)
            for s in sources
        ],
        last_run=run_out(last_run) if last_run else None,
    )


@router.get(
    "/companies/{company_id}/accuracy/trend", response_model=list[TrendPoint], tags=["accuracy"]
)
async def accuracy_trend(
    company_id: str,
    session: Session,
    today: Today,
    days: Annotated[int, Query(ge=1, le=365)] = 7,
) -> list[TrendPoint]:
    """One point per day and engine (the line chart). Days without a live run have no point."""
    await company_or_404(session, company_id)
    rows = await repo.accuracy_since(session, company_id, today - timedelta(days=days - 1))
    return [TrendPoint(date=r.run_date, engine=r.engine, accuracy=float(r.accuracy)) for r in rows]


@router.get(
    "/companies/{company_id}/accuracy/today", response_model=list[TodayItem], tags=["accuracy"]
)
async def accuracy_today(company_id: str, session: Session) -> list[TodayItem]:
    """Per engine: the latest live day, the one before it, and the change."""
    await company_or_404(session, company_id)
    items = []
    for engine, rows in sorted((await repo.accuracy_latest_two(session, company_id)).items()):
        latest, before = rows[0], rows[1] if len(rows) > 1 else None
        items.append(
            TodayItem(
                engine=engine,
                date=latest.run_date,
                accuracy=float(latest.accuracy),
                n_questions=latest.n_questions,
                previous_date=before.run_date if before else None,
                previous_accuracy=float(before.accuracy) if before else None,
                delta=round(float(latest.accuracy) - float(before.accuracy), 6) if before else None,
            )
        )
    return items


def detail_cell(answer: Any, score: Any) -> DetailCell:
    if answer.error is not None:
        return DetailCell(answer_id=answer.id, status="error")
    if score is None:
        return DetailCell(answer_id=answer.id, status="unscored")
    return DetailCell(
        answer_id=answer.id, status="scored", verdict=score.verdict, score=float(score.score)
    )


@router.get(
    "/companies/{company_id}/accuracy/details", response_model=DetailsOut, tags=["accuracy"]
)
async def accuracy_details(
    company_id: str,
    session: Session,
    today: Today,
    engine: Annotated[str, Query(description="engine id, or rag")],
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
) -> DetailsOut:
    """Fact questions (rows) by days (columns) for one engine; click a cell -> /api/answers/{id}."""
    await company_or_404(session, company_id)
    if engine not in known_engine_ids():
        raise HTTPException(422, f"Unknown engine '{engine}'")
    end = date_to or today
    start = date_from or end - timedelta(days=13)
    if start > end:
        raise HTTPException(422, "'from' must not be after 'to'")
    if (end - start).days >= MAX_DETAIL_DAYS:
        raise HTTPException(422, f"At most {MAX_DETAIL_DAYS} days at a time")

    cells = await repo.detail_cells(session, company_id, engine, start, end)
    by_question: dict[uuid.UUID, dict[str, DetailCell]] = {}
    for answer, score, run_date in cells:
        by_question.setdefault(answer.question_id, {})[run_date.isoformat()] = detail_cell(
            answer, score
        )
    questions = await repo.fact_questions(session, company_id)
    return DetailsOut(
        engine=engine,
        date_from=start,
        date_to=end,
        dates=sorted({run_date for _, _, run_date in cells}),
        rows=[
            DetailRow(question_id=q.id, code=q.code, text=q.text, cells=by_question.get(q.id, {}))
            for q in questions
        ],
    )


@router.get("/answers/{answer_id}", response_model=AnswerDetail, tags=["answers"])
async def answer_detail(answer_id: uuid.UUID, session: Session) -> AnswerDetail:
    """One answer with its score, citations, why finding and the previous day's answer."""
    ctx = await repo.answer_context(session, answer_id)
    if ctx is None:
        raise HTTPException(404, "Unknown answer")
    previous = None
    if ctx.previous:
        before, before_run, before_score = ctx.previous
        previous = PreviousAnswer(
            answer_id=before.id,
            run_date=before_run.run_date,
            text=before.text,
            verdict=before_score.verdict if before_score else None,
            score=float(before_score.score) if before_score else None,
        )
    score = ctx.score
    why = ctx.why
    return AnswerDetail(
        id=ctx.answer.id,
        engine=ctx.answer.engine,
        run_date=ctx.run.run_date,
        asked_at=ctx.answer.asked_at,
        question=question_out(ctx.question),
        text=ctx.answer.text,
        error=ctx.answer.error,
        score=ScoreOut(
            verdict=score.verdict,
            score=float(score.score),
            reason=score.reason,
            quote=score.quote,
            quote_verified=score.quote_verified,
            method=score.method,
        )
        if score
        else None,
        citations=[
            CitationOut(url=c.url, title=c.title, domain=c.domain, owner=c.owner)
            for c in ctx.citations
        ],
        why=WhyOut(
            source_type=why.source_type,
            source_url=why.source_url,
            evidence_quote=why.evidence_quote,
            explanation=why.explanation,
            suggested_fix=why.suggested_fix,
        )
        if why
        else None,
        previous=previous,
    )


@router.get("/companies/{company_id}/alerts", response_model=list[AlertOut], tags=["alerts"])
async def alerts(
    company_id: str,
    session: Session,
    today: Today,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> list[AlertOut]:
    await company_or_404(session, company_id)
    rows = await repo.alerts_since(session, company_id, today - timedelta(days=days - 1))
    return [
        AlertOut(
            id=a.id,
            run_date=a.run_date,
            kind=a.kind,
            severity=a.severity,
            engine=a.engine,
            question_code=q.code,
            question_text=q.text,
            summary=a.summary,
            before_answer_id=a.before_answer_id,
            after_answer_id=a.after_answer_id,
        )
        for a, q in rows
    ]


@router.get("/companies/{company_id}/runs", response_model=list[RunOut], tags=["runs"])
async def runs(
    company_id: str, session: Session, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[RunOut]:
    await company_or_404(session, company_id)
    return [run_out(r) for r in await repo.recent_runs(session, company_id, limit)]


@router.get("/companies/{company_id}/emails", response_model=list[EmailLogOut], tags=["emails"])
async def emails(
    company_id: str,
    session: Session,
    is_admin: Annotated[bool, Depends(optional_admin)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[EmailLogOut]:
    """The email log. Recipient addresses are only shown to the admin."""
    await company_or_404(session, company_id)
    return [
        EmailLogOut(
            id=e.id,
            kind=e.kind,
            subject=e.subject,
            status=e.status,
            error=e.error,
            sent_at=e.sent_at,
            created_at=e.created_at,
            recipient_count=len(e.recipients),
            recipients=list(e.recipients) if is_admin else None,
        )
        for e in await repo.recent_emails(session, company_id, limit)
    ]
