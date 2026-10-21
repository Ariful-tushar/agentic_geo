"""Small FastAPI dependencies (tests replace them)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.emails.smtp import Sender, send_mail


def get_today() -> date:
    """Today's date in the configured timezone (Europe/Helsinki)."""
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


def get_email_sender() -> Sender:
    """The function that sends mail (tests replace it with a fake)."""
    return send_mail
