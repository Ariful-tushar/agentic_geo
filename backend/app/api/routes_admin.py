"""Write endpoints (SPEC 9). Everything except the login check needs the `X-Admin-Token` header."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import is_admin, require_admin
from app.api.deps import get_email_sender
from app.api.routes_public import company_or_404
from app.db.models import Company
from app.db.session import get_session
from app.emails.commands import send_test_email
from app.emails.smtp import Sender
from app.jobs.runner import (
    JobAlreadyRunning,
    JobNotAvailable,
    JobRunner,
    JobStartError,
    get_job_runner,
    start_job,
)
from app.profiles.loader import ProfileError, import_profile, parse_profile
from app.schemas.api import (
    CompanyCreated,
    CreateCompanyIn,
    ImportIn,
    JobIn,
    JobName,
    JobStartOut,
    LoginIn,
    LoginOut,
    SettingsIn,
    SettingsOut,
    TestEmailOut,
)

router = APIRouter(prefix="/api", tags=["admin"])

Session = Annotated[AsyncSession, Depends(get_session)]
Runner = Annotated[JobRunner, Depends(get_job_runner)]
EmailSender = Annotated[Sender, Depends(get_email_sender)]
Admin = Depends(require_admin)

LOGIN_FAIL_DELAY_SECONDS = 0.5  # slows down password guessing


async def start_or_http_error(
    session: AsyncSession, runner: JobRunner, job: JobName, company_id: str
) -> JobStartOut:
    """start_job, with each failure turned into the right HTTP status."""
    try:
        return await start_job(session, runner, job, company_id)
    except JobNotAvailable as exc:
        raise HTTPException(501, str(exc)) from exc
    except JobAlreadyRunning as exc:
        raise HTTPException(409, f"{exc}") from exc
    except JobStartError as exc:
        raise HTTPException(502, f"Could not start the job: {exc}") from exc


@router.post("/admin/login", response_model=LoginOut)
async def login(body: LoginIn) -> LoginOut:
    """Checks the password. The dashboard then sends it as the `X-Admin-Token` header."""
    if not is_admin(body.password):
        await asyncio.sleep(LOGIN_FAIL_DELAY_SECONDS)
        raise HTTPException(401, "Wrong password")
    return LoginOut()


@router.patch(
    "/companies/{company_id}/settings",
    response_model=SettingsOut,
    dependencies=[Admin],
)
async def update_settings(company_id: str, body: SettingsIn, session: Session) -> SettingsOut:
    company = await company_or_404(session, company_id)
    if body.monitoring_enabled is not None:
        company.monitoring_enabled = body.monitoring_enabled
    if body.emails_enabled is not None:
        company.emails_enabled = body.emails_enabled
    if body.contact_emails is not None:
        company.contact_emails = [str(e) for e in body.contact_emails]
    await session.commit()
    return SettingsOut(
        company_id=company.id,
        monitoring_enabled=company.monitoring_enabled,
        emails_enabled=company.emails_enabled,
        contact_emails=list(company.contact_emails),
    )


@router.post(
    "/companies/{company_id}/jobs",
    response_model=JobStartOut,
    status_code=202,
    dependencies=[Admin],
)
async def start_company_job(
    company_id: str, body: JobIn, session: Session, runner: Runner
) -> JobStartOut:
    """Starts a job (ax, onboard, ...) through the JobRunner. 202 = started, not finished."""
    await company_or_404(session, company_id)
    return await start_or_http_error(session, runner, body.job, company_id)


@router.post(
    "/companies/{company_id}/test-email",
    response_model=TestEmailOut,
    dependencies=[Admin],
)
async def test_email(company_id: str, session: Session, sender: EmailSender) -> TestEmailOut:
    """Sends a test email to the contact emails (ignores the emails switch). The outcome is
    also written to the email log."""
    company = await company_or_404(session, company_id)
    result = await send_test_email(session, company, sender)
    return TestEmailOut(status=result.status, detail=result.detail)


async def save_profile_and_onboard(
    session: AsyncSession, runner: JobRunner, profile: CreateCompanyIn
) -> CompanyCreated:
    result = await import_profile(session, profile)
    created = CompanyCreated(
        company_id=profile.id,
        created=result.company_created,
        questions_added=result.questions_added,
        questions_kept=result.questions_kept,
        competitors_added=result.competitors_added,
        sources_added=result.sources_added,
    )
    try:  # the profile stays saved even if the job cannot start
        created.job = await start_or_http_error(session, runner, "onboard", profile.id)
    except HTTPException as exc:
        created.job_error = str(exc.detail)
    return created


@router.post("/companies", response_model=CompanyCreated, status_code=201, dependencies=[Admin])
async def create_company(
    profile: CreateCompanyIn, session: Session, runner: Runner
) -> CompanyCreated:
    """Creates a profile from JSON and starts the onboarding job. 409 if the id exists."""
    if await session.get(Company, profile.id) is not None:
        raise HTTPException(409, f"Company '{profile.id}' already exists")
    return await save_profile_and_onboard(session, runner, profile)


@router.post("/companies/import", response_model=CompanyCreated, dependencies=[Admin])
async def import_company(body: ImportIn, session: Session, runner: Runner) -> CompanyCreated:
    """Creates or updates a profile from YAML text (like the CLI), then starts onboarding.
    Importing the same file twice adds nothing; questions are never changed."""
    try:
        profile = parse_profile(body.yaml)
    except ProfileError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await save_profile_and_onboard(session, runner, profile)
