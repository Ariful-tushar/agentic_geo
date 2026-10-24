"""Repository helpers: small, typed database functions used by the loader and agents."""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Select, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Alert,
    Answer,
    Citation,
    Company,
    Competitor,
    CompetitorEvent,
    DailyAccuracy,
    EmailLog,
    FaqDraft,
    KnowledgeSource,
    Mention,
    PublicQuestion,
    Question,
    ReadinessCheck,
    Run,
    Score,
    WhyFinding,
)
from app.schemas.profile import ProfileIn

# Multi-row INSERT needs the same keys in every row, so generic questions get explicit Nones.
NO_FACT_FIELDS: dict[str, None] = dict.fromkeys(
    ("expected_answer", "expected_value", "tolerance", "unit", "expected_source_url")
)


@dataclass
class ImportResult:
    company_created: bool = False
    competitors_added: int = 0
    sources_added: int = 0
    questions_added: int = 0
    questions_kept: int = 0
    deactivated: int = 0


async def upsert_company(session: AsyncSession, profile: ProfileIn) -> bool:
    """Create or update the company row. Returns True when it was created."""
    company = await session.get(Company, profile.id)
    created = company is None
    if company is None:
        company = Company(id=profile.id, onboarding_status="pending")
        session.add(company)
    company.name = profile.name
    company.aliases = profile.aliases
    company.domains = profile.domains
    company.wikipedia_title = profile.wikipedia_title
    if created:  # a re-import never overwrites the real addresses (the seed has a placeholder)
        company.contact_emails = [str(e) for e in profile.contact_emails]
    company.faq_source_urls = [str(u) for u in profile.faq_source_urls]
    company.monitoring_enabled = profile.monitoring_enabled
    company.emails_enabled = profile.emails_enabled
    await session.flush()
    return created


async def sync_competitors(session: AsyncSession, profile: ProfileIn) -> tuple[int, int]:
    """Upsert listed competitors as active; mark unlisted ones inactive. Returns (added, off)."""
    rows = (
        await session.scalars(select(Competitor).where(Competitor.company_id == profile.id))
    ).all()
    existing = {c.name.lower(): c for c in rows}
    listed = {c.name.lower() for c in profile.competitors}
    added = 0
    for item in profile.competitors:
        row = existing.get(item.name.lower())
        if row is None:
            row = Competitor(company_id=profile.id, name=item.name)
            session.add(row)
            added += 1
        row.aliases, row.domains, row.active = item.aliases, item.domains, True
    deactivated = 0
    for key, row in existing.items():
        if key not in listed and row.active:
            row.active = False
            deactivated += 1
    await session.flush()
    return added, deactivated


async def sync_knowledge_sources(session: AsyncSession, profile: ProfileIn) -> tuple[int, int]:
    """Same rule as competitors: listed URLs active, unlisted URLs inactive."""
    rows = (
        await session.scalars(
            select(KnowledgeSource).where(KnowledgeSource.company_id == profile.id)
        )
    ).all()
    existing = {s.url: s for s in rows}
    listed = {str(u) for u in profile.knowledge_sources}
    added = 0
    for url in listed:
        row = existing.get(url)
        if row is None:
            session.add(KnowledgeSource(company_id=profile.id, url=url))
            added += 1
        else:
            row.active = True
    deactivated = 0
    for url, row in existing.items():
        if url not in listed and row.active:
            row.active = False
            deactivated += 1
    await session.flush()
    return added, deactivated


async def create_questions(session: AsyncSession, profile: ProfileIn) -> tuple[int, int]:
    """Insert questions that do not exist yet; existing codes are never changed."""
    values = [
        {
            "company_id": profile.id,
            "kind": "fact",
            "code": q.code,
            "text": q.text,
            "expected_answer": q.expected_answer,
            "expected_value": q.expected_value,
            "tolerance": q.tolerance,
            "unit": q.unit,
            "expected_source_url": str(q.expected_source_url) if q.expected_source_url else None,
        }
        for q in profile.fact_questions
    ] + [
        {
            **NO_FACT_FIELDS,
            "company_id": profile.id,
            "kind": "generic",
            "code": q.code,
            "text": q.text,
        }
        for q in profile.generic_questions
    ]
    stmt = (
        insert(Question)
        .values(values)
        .on_conflict_do_nothing(index_elements=["company_id", "code"])
        .returning(Question.id)
    )
    added = len((await session.execute(stmt)).all())
    return added, len(values) - added


async def set_onboarding(
    session: AsyncSession, company_id: str, status: str, error: str | None = None
) -> None:
    """Set companies.onboarding_status / onboarding_error and commit."""
    company = await session.get(Company, company_id)
    if company is None:
        raise ValueError(f"unknown company '{company_id}'")
    company.onboarding_status = status
    company.onboarding_error = error
    await session.commit()


SIMULATED = "simulated"  # runs.trigger of seeded demo history: charts only, never alerts or emails


def live_daily_accuracy(company_id: str, mode: str = "live") -> Select[tuple[DailyAccuracy]]:
    """Accuracy rows the API, alerts and emails may use: real live runs only, never dev and
    never simulated demo history (only `accuracy_since` for the chart adds the simulated days).

    `mode="dev"` is only for the dev preview of an email."""
    return (
        select(DailyAccuracy)
        .join(Run, Run.id == DailyAccuracy.run_id)
        .where(
            DailyAccuracy.company_id == company_id,
            DailyAccuracy.mode == mode,
            Run.trigger != SIMULATED,
        )
    )


def live_competitor_events(company_id: str, mode: str = "live") -> Select[tuple[CompetitorEvent]]:
    """Competitor events of live runs only (events of dev runs are trial data)."""
    return (
        select(CompetitorEvent)
        .join(Answer, Answer.id == CompetitorEvent.answer_id)
        .join(Run, Run.id == Answer.run_id)
        .where(
            CompetitorEvent.company_id == company_id,
            Run.mode == mode,
            Run.trigger != SIMULATED,
        )
    )


# ---- read queries for the API (SPEC 9): live runs only ---------------------------------------


async def latest_live_runs(session: AsyncSession) -> dict[str, Run]:
    """The most recent live run of every company."""
    runs = (
        await session.scalars(
            select(Run)
            .where(Run.mode == "live", Run.trigger != SIMULATED)
            .order_by(Run.started_at.desc())
        )
    ).all()
    latest: dict[str, Run] = {}
    for run in runs:
        latest.setdefault(run.company_id, run)
    return latest


async def list_companies(session: AsyncSession) -> list[tuple[Company, Run | None]]:
    companies = (await session.scalars(select(Company).order_by(Company.name))).all()
    latest = await latest_live_runs(session)
    return [(c, latest.get(c.id)) for c in companies]


async def get_company_parts(
    session: AsyncSession, company_id: str
) -> tuple[Company, list[Competitor], list[Question], list[KnowledgeSource], Run | None] | None:
    company = await session.get(Company, company_id)
    if company is None:
        return None
    competitors = (
        await session.scalars(
            select(Competitor).where(Competitor.company_id == company_id).order_by(Competitor.name)
        )
    ).all()
    questions = (
        await session.scalars(
            select(Question).where(Question.company_id == company_id).order_by(Question.code)
        )
    ).all()
    sources = (
        await session.scalars(
            select(KnowledgeSource)
            .where(KnowledgeSource.company_id == company_id)
            .order_by(KnowledgeSource.url)
        )
    ).all()
    latest = (await latest_live_runs(session)).get(company_id)
    return company, list(competitors), list(questions), list(sources), latest


async def accuracy_since(
    session: AsyncSession, company_id: str, since: date
) -> list[tuple[DailyAccuracy, bool]]:
    """Chart points of live runs, each flagged: is this day simulated demo history?"""
    stmt = (
        select(DailyAccuracy, Run.trigger == SIMULATED)
        .join(Run, Run.id == DailyAccuracy.run_id)
        .where(
            DailyAccuracy.company_id == company_id,
            DailyAccuracy.mode == "live",
            DailyAccuracy.run_date >= since,
        )
        .order_by(DailyAccuracy.run_date, DailyAccuracy.engine)
    )
    return [(row, bool(simulated)) for row, simulated in (await session.execute(stmt)).all()]


async def simulated_dates(
    session: AsyncSession, company_id: str, date_from: date, date_to: date
) -> list[date]:
    """Days in the range that are seeded demo history (no answers are stored for them)."""
    stmt = (
        select(Run.run_date)
        .where(
            Run.company_id == company_id,
            Run.kind == "ax",
            Run.mode == "live",
            Run.trigger == SIMULATED,
            Run.run_date.between(date_from, date_to),
        )
        .order_by(Run.run_date)
    )
    return list((await session.scalars(stmt)).all())


async def accuracy_latest_two(
    session: AsyncSession, company_id: str, mode: str = "live"
) -> dict[str, list[DailyAccuracy]]:
    """Per engine: the latest live day and the one before it (newest first)."""
    rows = (
        await session.scalars(
            live_daily_accuracy(company_id, mode).order_by(DailyAccuracy.run_date.desc())
        )
    ).all()
    per_engine: dict[str, list[DailyAccuracy]] = {}
    for row in rows:
        if len(per_engine.setdefault(row.engine, [])) < 2:
            per_engine[row.engine].append(row)
    return per_engine


async def fact_questions(session: AsyncSession, company_id: str) -> list[Question]:
    return list(
        (
            await session.scalars(
                select(Question)
                .where(Question.company_id == company_id, Question.kind == "fact")
                .order_by(Question.code)
            )
        ).all()
    )


async def detail_cells(
    session: AsyncSession, company_id: str, engine: str, date_from: date, date_to: date
) -> list[tuple[Answer, Score | None, date]]:
    """Fact-question answers of one engine in live runs between two dates."""
    rows = await session.execute(
        select(Answer, Score, Run.run_date)
        .join(Run, Run.id == Answer.run_id)
        .join(Question, Question.id == Answer.question_id)
        .outerjoin(Score, Score.answer_id == Answer.id)
        .where(
            Run.company_id == company_id,
            Run.mode == "live",
            Run.kind == "ax",
            Run.run_date.between(date_from, date_to),
            Answer.engine == engine,
            Question.kind == "fact",
        )
        .order_by(Run.run_date)
    )
    return [(a, s, d) for a, s, d in rows.all()]


@dataclass
class AnswerContext:
    answer: Answer
    run: Run
    question: Question
    score: Score | None
    citations: list[Citation]
    why: WhyFinding | None
    previous: tuple[Answer, Run, Score | None] | None


async def answer_context(session: AsyncSession, answer_id: uuid.UUID) -> AnswerContext | None:
    """One answer with everything around it. Answers of dev runs are not available."""
    row = (
        await session.execute(
            select(Answer, Run, Question)
            .join(Run, Run.id == Answer.run_id)
            .join(Question, Question.id == Answer.question_id)
            .where(Answer.id == answer_id, Run.mode == "live")
        )
    ).first()
    if row is None:
        return None
    answer, run, question = row
    score = await session.scalar(select(Score).where(Score.answer_id == answer.id))
    citations = (
        await session.scalars(
            select(Citation).where(Citation.answer_id == answer.id).order_by(Citation.url)
        )
    ).all()
    why = await session.scalar(select(WhyFinding).where(WhyFinding.answer_id == answer.id))
    earlier = (
        await session.execute(
            select(Answer, Run, Score)
            .join(Run, Run.id == Answer.run_id)
            .outerjoin(Score, Score.answer_id == Answer.id)
            .where(
                Run.company_id == run.company_id,
                Run.mode == "live",
                Run.kind == "ax",
                Run.run_date < run.run_date,
                Answer.engine == answer.engine,
                Answer.question_id == answer.question_id,
                Answer.error.is_(None),
                Answer.text.is_not(None),
            )
            .order_by(Run.run_date.desc())
            .limit(1)
        )
    ).first()
    previous = (earlier[0], earlier[1], earlier[2]) if earlier else None
    return AnswerContext(answer, run, question, score, list(citations), why, previous)


async def alerts_since(
    session: AsyncSession, company_id: str, since: date
) -> list[tuple[Alert, Question]]:
    rows = await session.execute(
        select(Alert, Question)
        .join(Question, Question.id == Alert.question_id)
        .where(Alert.company_id == company_id, Alert.run_date >= since)
        .order_by(Alert.run_date.desc(), Alert.severity, Question.code)
    )
    return [(a, q) for a, q in rows.all()]


async def public_questions(session: AsyncSession, company_id: str) -> list[PublicQuestion]:
    """Every public question found so far, newest first."""
    stmt = (
        select(PublicQuestion)
        .where(PublicQuestion.company_id == company_id)
        .order_by(PublicQuestion.first_seen_at.desc(), PublicQuestion.text)
    )
    return list((await session.scalars(stmt)).all())


async def faq_drafts(session: AsyncSession, company_id: str) -> list[FaqDraft]:
    stmt = (
        select(FaqDraft)
        .where(FaqDraft.company_id == company_id)
        .order_by(FaqDraft.created_at.desc(), FaqDraft.question)
    )
    return list((await session.scalars(stmt)).all())


async def create_readiness_check(
    session: AsyncSession, company_id: str, url: str
) -> ReadinessCheck:
    check = ReadinessCheck(company_id=company_id, url=url, status="queued")
    session.add(check)
    await session.commit()
    await session.refresh(check)
    return check


async def readiness_checks(session: AsyncSession, company_id: str) -> list[ReadinessCheck]:
    stmt = (
        select(ReadinessCheck)
        .where(ReadinessCheck.company_id == company_id)
        .order_by(ReadinessCheck.created_at.desc())
        .limit(50)
    )
    return list((await session.scalars(stmt)).all())


async def readiness_check(session: AsyncSession, check_id: uuid.UUID) -> ReadinessCheck | None:
    return await session.get(ReadinessCheck, check_id)


async def competitor_events_since(
    session: AsyncSession, company_id: str, since: date, engine: str | None
) -> list[tuple[CompetitorEvent, Question]]:
    stmt = (
        live_competitor_events(company_id)
        .join(Question, Question.id == CompetitorEvent.question_id)
        .add_columns(Question)
        .where(CompetitorEvent.run_date >= since)
        .order_by(CompetitorEvent.run_date.desc(), CompetitorEvent.engine, Question.code)
    )
    if engine:
        stmt = stmt.where(CompetitorEvent.engine == engine)
    return [(e, q) for e, q in (await session.execute(stmt)).all()]


async def company_mention_counts(
    session: AsyncSession, company_id: str, since: date
) -> list[tuple[date, str, int, int]]:
    """(day, engine, generic answers, answers that name the company) for live runs.

    Answers with an error have no text and are not counted."""
    named = exists().where(Mention.answer_id == Answer.id, Mention.brand_type == "company")
    stmt = (
        select(
            Run.run_date,
            Answer.engine,
            func.count(Answer.id),
            func.count(Answer.id).filter(named),
        )
        .join(Run, Run.id == Answer.run_id)
        .join(Question, Question.id == Answer.question_id)
        .where(
            Answer.company_id == company_id,
            Question.kind == "generic",
            Answer.error.is_(None),
            Answer.text.is_not(None),
            Run.mode == "live",
            Run.trigger != SIMULATED,
            Run.run_date >= since,
        )
        .group_by(Run.run_date, Answer.engine)
        .order_by(Run.run_date, Answer.engine)
    )
    return [(d, e, int(n), int(c)) for d, e, n, c in (await session.execute(stmt)).all()]


async def recent_runs(session: AsyncSession, company_id: str, limit: int) -> list[Run]:
    stmt = (
        select(Run)
        .where(Run.company_id == company_id, Run.mode == "live", Run.trigger != SIMULATED)
        .order_by(Run.started_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


# ---- emails -----------------------------------------------------------------------------------


async def unsent_warning_alerts(
    session: AsyncSession, company_id: str
) -> list[tuple[Alert, Question]]:
    """`warning` alerts that were never emailed (each alert is emailed only once)."""
    rows = await session.execute(
        select(Alert, Question)
        .join(Question, Question.id == Alert.question_id)
        .where(
            Alert.company_id == company_id,
            Alert.severity == "warning",
            Alert.emailed.is_(False),
        )
        .order_by(Alert.run_date, Alert.engine, Question.code)
    )
    return [(a, q) for a, q in rows.all()]


async def recent_emails(session: AsyncSession, company_id: str, limit: int) -> list[EmailLog]:
    stmt = (
        select(EmailLog)
        .where(EmailLog.company_id == company_id)
        .order_by(EmailLog.created_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())
