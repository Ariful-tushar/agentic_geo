"""Sending mail through Gmail SMTP, and the `email_log` row for every send (SPEC 8.6).

Port 465 uses SSL from the start (`use_tls`); any other port (587) upgrades with STARTTLS
(`start_tls`). Checked in the installed aiosmtplib 5.1.3 (`aiosmtplib.send` signature).
The app password is only passed to the SMTP library: it is never logged, printed or stored.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

import aiosmtplib
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Company, EmailLog

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
PREVIEW_DIR = BACKEND_DIR / "logs"
MAX_ERROR_CHARS = 300


@dataclass(frozen=True)
class Mail:
    subject: str
    text: str
    html: str


@dataclass(frozen=True)
class EmailResult:
    """status: sent | failed | skipped | preview (dev mode: nothing is sent)."""

    status: str
    detail: str = ""


Sender = Callable[[list[str], Mail], Awaitable[None]]


class EmailNotConfigured(Exception):
    """SMTP_USER or SMTP_APP_PASSWORD is missing."""


def build_message(recipients: list[str], mail: Mail) -> EmailMessage:
    settings = get_settings()
    message = EmailMessage()
    message["Subject"] = mail.subject
    message["From"] = formataddr((settings.email_from_name, settings.smtp_user))
    message["To"] = ", ".join(recipients)
    message.set_content(mail.text)
    message.add_alternative(mail.html, subtype="html")
    return message


async def send_mail(recipients: list[str], mail: Mail) -> None:
    """Send one message with Gmail SMTP. Raises on any problem."""
    settings = get_settings()
    if not settings.smtp_user or not settings.smtp_app_password:
        raise EmailNotConfigured("SMTP_USER and SMTP_APP_PASSWORD are not set")
    await aiosmtplib.send(
        build_message(recipients, mail),
        sender=settings.smtp_user,
        recipients=recipients,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_app_password,
        use_tls=settings.smtp_port == 465,
        start_tls=settings.smtp_port != 465,
        timeout=30,
    )


def error_text(exc: Exception) -> str:
    """A short, safe description of a sending error (the password is never part of it)."""
    text = f"{type(exc).__name__}: {exc}"
    password = get_settings().smtp_app_password
    if password:
        text = text.replace(password, "***")
    return text[:MAX_ERROR_CHARS]


async def deliver(
    session: AsyncSession,
    company: Company,
    kind: str,
    mail: Mail,
    sender: Sender = send_mail,
) -> EmailResult:
    """Send `mail` to the company's contact emails and log the outcome.

    No recipients -> a `skipped` row (reason "no recipients"), nothing is sent."""
    recipients = list(company.contact_emails)
    row = EmailLog(company_id=company.id, kind=kind, recipients=recipients, subject=mail.subject)
    if not recipients:
        row.status, row.error = "skipped", "no recipients"
        session.add(row)
        await session.commit()
        return EmailResult("skipped", "no recipients")
    try:
        await sender(recipients, mail)
    except Exception as exc:  # any sending problem is logged, never raised to the caller
        row.status, row.error = "failed", error_text(exc)
        log.warning("email %s for %s failed: %s", kind, company.id, row.error)
    else:
        row.status, row.sent_at = "sent", datetime.now(UTC)
    session.add(row)
    await session.commit()
    return EmailResult(row.status, row.error or "")


def write_preview(mail: Mail, name: str) -> Path:
    """Dev mode: save the HTML to logs/<name>.html so it can be opened in a browser."""
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    path = PREVIEW_DIR / f"{name}.html"
    comment = f"<!-- Subject: {mail.subject.replace('--', '- -')} -->\n"
    path.write_text(comment + mail.html, encoding="utf-8")
    return path
