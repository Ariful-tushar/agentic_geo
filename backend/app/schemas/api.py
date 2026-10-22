"""Request and response models of the API (SPEC section 9). All responses are Pydantic models."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.profile import ProfileIn

JobName = Literal["daily", "ax", "competitor", "faq", "onboard"]


# ---- small shared pieces ---------------------------------------------------------------------


class Health(BaseModel):
    status: str
    db: bool


class EngineOut(BaseModel):
    id: str
    label: str
    web_search: bool
    enabled: bool


class RunOut(BaseModel):
    id: uuid.UUID
    kind: str
    mode: str
    status: str
    trigger: str
    run_date: date
    started_at: datetime
    finished_at: datetime | None = None
    # the useful part of runs.details: answers, warnings, accuracy per engine, skipped engines
    summary: dict[str, Any] = Field(default_factory=dict)


# ---- companies -------------------------------------------------------------------------------


class CompanyListItem(BaseModel):
    id: str
    name: str
    onboarding_status: str
    monitoring_enabled: bool
    last_run: RunOut | None = None


class CompetitorOut(BaseModel):
    id: uuid.UUID
    name: str
    aliases: list[str]
    domains: list[str]
    active: bool


class QuestionOut(BaseModel):
    id: uuid.UUID
    code: str
    kind: str
    text: str
    expected_answer: str | None = None
    expected_value: float | None = None
    tolerance: float | None = None
    unit: str | None = None
    expected_source_url: str | None = None


class SourceOut(BaseModel):
    url: str
    status: str
    last_built_at: datetime | None = None
    active: bool


class CompanyDetail(BaseModel):
    id: str
    name: str
    aliases: list[str]
    domains: list[str]
    wikipedia_title: str | None = None
    contact_email_count: int
    # the addresses themselves are personal data: only an admin gets them
    contact_emails: list[str] | None = None
    faq_source_urls: list[str]
    monitoring_enabled: bool
    emails_enabled: bool
    onboarding_status: str
    onboarding_error: str | None = None
    competitors: list[CompetitorOut]
    questions: list[QuestionOut]
    knowledge_sources: list[SourceOut]
    last_run: RunOut | None = None


# ---- accuracy --------------------------------------------------------------------------------


class TrendPoint(BaseModel):
    date: date
    engine: str
    accuracy: float
    simulated: bool = False  # seeded demo history, shown as such in the chart


class TodayItem(BaseModel):
    engine: str
    date: date
    accuracy: float
    n_questions: int
    previous_date: date | None = None
    previous_accuracy: float | None = None
    delta: float | None = None


class DetailCell(BaseModel):
    answer_id: uuid.UUID
    status: Literal["scored", "error", "unscored"]
    verdict: str | None = None
    score: float | None = None


class DetailRow(BaseModel):
    question_id: uuid.UUID
    code: str
    text: str
    cells: dict[str, DetailCell]  # key = ISO date; a missing key means "no answer that day"


class DetailsOut(BaseModel):
    engine: str
    date_from: date
    date_to: date
    dates: list[date]
    simulated_dates: list[date] = []  # demo history days: no answers are stored for them
    rows: list[DetailRow]


# ---- one answer ------------------------------------------------------------------------------


class ScoreOut(BaseModel):
    verdict: str
    score: float
    reason: str | None = None
    quote: str | None = None
    quote_verified: bool
    method: str


class CitationOut(BaseModel):
    url: str
    title: str | None = None
    domain: str | None = None
    owner: str


class WhyOut(BaseModel):
    source_type: str
    source_url: str | None = None
    evidence_quote: str | None = None
    explanation: str | None = None
    suggested_fix: str | None = None


class PreviousAnswer(BaseModel):
    answer_id: uuid.UUID
    run_date: date
    text: str | None = None
    verdict: str | None = None
    score: float | None = None


class AnswerDetail(BaseModel):
    id: uuid.UUID
    engine: str
    run_date: date
    asked_at: datetime
    question: QuestionOut
    text: str | None = None
    error: str | None = None
    score: ScoreOut | None = None
    citations: list[CitationOut]
    why: WhyOut | None = None
    previous: PreviousAnswer | None = None


class AlertOut(BaseModel):
    id: uuid.UUID
    run_date: date
    kind: str
    severity: str
    engine: str
    question_code: str
    question_text: str
    summary: str
    before_answer_id: uuid.UUID | None = None
    after_answer_id: uuid.UUID | None = None


# ---- admin -----------------------------------------------------------------------------------


class LoginIn(BaseModel):
    password: str


class LoginOut(BaseModel):
    ok: bool = True


class SettingsIn(BaseModel):
    monitoring_enabled: bool | None = None
    emails_enabled: bool | None = None
    contact_emails: list[EmailStr] | None = None


class SettingsOut(BaseModel):
    company_id: str
    monitoring_enabled: bool
    emails_enabled: bool
    contact_emails: list[str]


class JobIn(BaseModel):
    job: JobName


class JobStartOut(BaseModel):
    job: JobName
    company_id: str
    runner: str
    status: str  # started
    detail: str = ""


class ImportIn(BaseModel):
    yaml: str = Field(min_length=1)


class CompanyCreated(BaseModel):
    company_id: str
    created: bool
    questions_added: int
    questions_kept: int
    competitors_added: int
    sources_added: int
    job: JobStartOut | None = None
    job_error: str | None = None


# the create endpoint takes the profile itself
CreateCompanyIn = ProfileIn


# ---- emails ----------------------------------------------------------------------------------


class EmailLogOut(BaseModel):
    id: uuid.UUID
    kind: str  # daily_report | alert | test
    subject: str
    status: str  # sent | failed | skipped
    error: str | None = None
    sent_at: datetime | None = None
    created_at: datetime
    recipient_count: int
    recipients: list[str] | None = None  # only for the admin, like contact_emails


class TestEmailOut(BaseModel):
    __test__ = False  # not a pytest class

    status: str  # sent | failed | skipped
    detail: str = ""
