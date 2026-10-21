"""CLI side of the emails: `send-report`, `send-alerts`, `send-test-email` (SPEC 11).

Each command opens its own database session, prints one line about what happened and returns
the process exit code (0 = sent, preview or a normal skip; 1 = sending failed)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_today
from app.config import get_settings
from app.db.models import Company
from app.db.session import get_engine, get_sessionmaker
from app.emails import alert, report, templates
from app.emails.smtp import EmailResult, Sender, deliver, send_mail

WHAT = {"report": "Daily report", "alerts": "Alert email", "test": "Test email"}


async def send_test_email(
    session: AsyncSession, company: Company, sender: Sender = send_mail
) -> EmailResult:
    """A setup check: it ignores the `emails_enabled` switch."""
    mail = templates.build_test_mail(company.name, get_settings().dashboard_url)
    return await deliver(session, company, "test", mail, sender)


def describe(result: EmailResult, what: str) -> str:
    if result.status == "sent":
        return f"{what}: sent."
    if result.status == "preview":
        return f"{what}: dev mode, nothing sent. Preview file: {result.detail}"
    return f"{what}: {result.status}" + (f" ({result.detail})" if result.detail else "") + "."


async def run_email_command(kind: str, company_id: str, mode: str, force: bool) -> int:
    today = get_today()
    try:
        async with get_sessionmaker()() as session:
            company = await session.get(Company, company_id)
            if company is None:
                print(f"Error: unknown company '{company_id}'")
                return 1
            if kind == "report":
                result = await report.send_report(
                    session, company, mode=mode, today=today, force=force
                )
            elif kind == "alerts":
                result = await alert.send_alerts(session, company, mode=mode, today=today)
            else:
                result = await send_test_email(session, company)
    finally:
        await get_engine().dispose()
    print(describe(result, WHAT[kind]))
    return 1 if result.status == "failed" else 0
