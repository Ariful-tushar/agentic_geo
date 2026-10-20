"""SQLAlchemy models for every table in SPEC section 6."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

TextList = ARRAY(Text)


def _in(column: str, values: tuple[str, ...]) -> CheckConstraint:
    quoted = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=f"ck_{column}")


class Base(DeclarativeBase):
    pass


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _company_fk() -> Mapped[str]:
    return mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)


def _answer_fk(unique: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(
        ForeignKey("answers.id", ondelete="CASCADE"), index=not unique, unique=unique
    )


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        _in("onboarding_status", ("pending", "building", "ready", "failed")),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(TextList, default=list)
    domains: Mapped[list[str]] = mapped_column(TextList, default=list)
    wikipedia_title: Mapped[str | None] = mapped_column(Text)
    contact_emails: Mapped[list[str]] = mapped_column(TextList, default=list)
    faq_source_urls: Mapped[list[str]] = mapped_column(TextList, default=list)
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    emails_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    onboarding_status: Mapped[str] = mapped_column(Text, default="pending")
    onboarding_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Competitor(Base):
    __tablename__ = "competitors"
    __table_args__ = (UniqueConstraint("company_id", "name"),)

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[str] = _company_fk()
    name: Mapped[str] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(TextList, default=list)
    domains: Mapped[list[str]] = mapped_column(TextList, default=list)
    # False when a re-import no longer lists it; agents ignore inactive rows.
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = _created()


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("company_id", "code"), _in("kind", ("fact", "generic")))

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[str] = _company_fk()
    code: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    expected_answer: Mapped[str | None] = mapped_column(Text)
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric)
    tolerance: Mapped[Decimal | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(Text)
    expected_source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (UniqueConstraint("company_id", "url"),)

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[str] = _company_fk()
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending")
    last_built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # False when a re-import no longer lists it; onboarding ignores inactive rows.
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = _created()


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (
        _in("date_kind", ("published", "modified")),
        _in("status", ("ok", "blocked_by_robots", "skipped_non_html", "http_error", "fetch_error")),
    )

    id: Mapped[uuid.UUID] = _id()
    url: Mapped[str] = mapped_column(Text, unique=True)
    final_url: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    h1: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    published_date: Mapped[date | None] = mapped_column(Date)
    date_kind: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    http_status: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("company_id", "kind", "run_date"),
        _in("kind", ("ax", "competitor", "faq", "daily", "onboard")),
        _in("trigger", ("schedule", "manual")),
        _in("status", ("running", "completed", "partial", "failed", "skipped")),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[str] = _company_fk()
    kind: Mapped[str] = mapped_column(Text)
    run_date: Mapped[date] = mapped_column(Date)
    trigger: Mapped[str] = mapped_column(Text, default="manual")
    status: Mapped[str] = mapped_column(Text, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created()


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("run_id", "question_id", "engine"),)

    id: Mapped[uuid.UUID] = _id()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[str] = _company_fk()
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    engine: Mapped[str] = mapped_column(Text)
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    text: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Citation(Base):
    __tablename__ = "citations"
    __table_args__ = (
        UniqueConstraint("answer_id", "url"),
        _in("owner", ("company", "competitor", "third_party")),
    )

    id: Mapped[uuid.UUID] = _id()
    answer_id: Mapped[uuid.UUID] = _answer_fk()
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(Text, default="third_party")
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("competitors.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = (
        _in("verdict", ("correct", "partial", "wrong", "no_answer")),
        _in("method", ("judge", "numeric")),
    )

    id: Mapped[uuid.UUID] = _id()
    answer_id: Mapped[uuid.UUID] = _answer_fk(unique=True)
    verdict: Mapped[str] = mapped_column(Text)
    score: Mapped[Decimal] = mapped_column(Numeric)
    reason: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text)
    quote_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    method: Mapped[str] = mapped_column(Text, default="judge")
    created_at: Mapped[datetime] = _created()


class DailyAccuracy(Base):
    __tablename__ = "daily_accuracy"
    __table_args__ = (UniqueConstraint("company_id", "run_date", "engine"),)

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[str] = _company_fk()
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    run_date: Mapped[date] = mapped_column(Date)
    engine: Mapped[str] = mapped_column(Text)
    accuracy: Mapped[Decimal] = mapped_column(Numeric)
    n_questions: Mapped[int] = mapped_column(Integer)
    n_correct: Mapped[int] = mapped_column(Integer, default=0)
    n_partial: Mapped[int] = mapped_column(Integer, default=0)
    n_wrong: Mapped[int] = mapped_column(Integer, default=0)
    n_no_answer: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = _created()


class WhyFinding(Base):
    __tablename__ = "why_findings"
    __table_args__ = (
        _in(
            "source_type",
            ("cited_page", "wikipedia", "own_site", "model_memory", "not_answered", "unknown"),
        ),
    )

    id: Mapped[uuid.UUID] = _id()
    answer_id: Mapped[uuid.UUID] = _answer_fk(unique=True)
    source_type: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    suggested_fix: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Mention(Base):
    __tablename__ = "mentions"
    __table_args__ = (
        UniqueConstraint("answer_id", "name"),
        _in("brand_type", ("company", "competitor", "other")),
    )

    id: Mapped[uuid.UUID] = _id()
    answer_id: Mapped[uuid.UUID] = _answer_fk()
    brand_type: Mapped[str] = mapped_column(Text)
    competitor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("competitors.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(Text)
    rank: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()


class CompetitorEvent(Base):
    __tablename__ = "competitor_events"
    __table_args__ = (
        _in("kind", ("competitor_ahead", "company_missing")),
        _in("status", ("new", "analysed")),
        _in("report_status", ("found", "nothing_found")),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[str] = _company_fk()
    run_date: Mapped[date] = mapped_column(Date)
    answer_id: Mapped[uuid.UUID] = _answer_fk(unique=True)
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    engine: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    competitors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    company_rank: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="new")
    report_status: Mapped[str | None] = mapped_column(Text)
    report: Mapped[str | None] = mapped_column(Text)
    analysed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("company_id", "run_date", "kind", "engine", "question_id"),
        _in("kind", ("score_drop", "company_dropped", "competitor_overtook", "score_improved")),
        _in("severity", ("warning", "info")),
    )

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[str] = _company_fk()
    run_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    engine: Mapped[str] = mapped_column(Text)
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="CASCADE"), index=True
    )
    before_answer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("answers.id", ondelete="SET NULL")
    )
    after_answer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("answers.id", ondelete="SET NULL")
    )
    summary: Mapped[str] = mapped_column(Text)
    emailed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _created()


class PublicQuestion(Base):
    __tablename__ = "public_questions"
    __table_args__ = (UniqueConstraint("company_id", "normalized"),)

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[str] = _company_fk()
    source_url: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    normalized: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    relevant: Mapped[bool | None] = mapped_column(Boolean)
    relevance_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class FaqDraft(Base):
    __tablename__ = "faq_drafts"

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[str] = _company_fk()
    public_question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_questions.id", ondelete="CASCADE"), unique=True
    )
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    source_urls: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = _created()


class ReadinessCheck(Base):
    __tablename__ = "readiness_checks"
    __table_args__ = (_in("status", ("queued", "running", "done", "failed")),)

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[str] = _company_fk()
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="queued")
    n_questions: Mapped[int | None] = mapped_column(Integer)
    n_answered: Mapped[int | None] = mapped_column(Integer)
    n_partial: Mapped[int | None] = mapped_column(Integer)
    results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    missing: Mapped[list[Any] | None] = mapped_column(JSONB)
    suggestions: Mapped[list[Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class EmailLog(Base):
    __tablename__ = "email_log"
    __table_args__ = (_in("kind", ("daily_report", "alert", "test")),)

    id: Mapped[uuid.UUID] = _id()
    company_id: Mapped[str] = _company_fk()
    kind: Mapped[str] = mapped_column(Text)
    recipients: Mapped[list[str]] = mapped_column(TextList, default=list)
    subject: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = _id()
    role: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    prompt_hash: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric, default=0)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class LlmCache(Base):
    __tablename__ = "llm_cache"

    prompt_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()
