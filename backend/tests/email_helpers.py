"""Helpers for the email tests: a fake sender and a company with real-looking recipients."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company
from app.emails.smtp import Mail

RECIPIENTS = ["boss@example.org", "team@example.org"]


class FakeSender:
    """Records what would be sent; can pretend that sending fails."""

    def __init__(self) -> None:
        self.sent: list[tuple[list[str], Mail]] = []
        self.error: Exception | None = None

    async def __call__(self, recipients: list[str], mail: Mail) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append((recipients, mail))


async def set_contacts(session: AsyncSession, emails: list[str], enabled: bool = True) -> Company:
    company = await session.get(Company, "kemira")
    assert company is not None
    company.contact_emails = emails
    company.emails_enabled = enabled
    await session.commit()
    return company
