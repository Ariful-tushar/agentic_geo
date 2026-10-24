"""Emails (SPEC 8.6): SMTP settings, the log, the daily report, the alert email and the dev preview.

No real mail is sent: a FakeSender records the messages, aiosmtplib.send is replaced."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alert, Company, EmailLog
from app.emails import alert, report, smtp, templates
from app.emails.commands import send_test_email
from app.emails.smtp import EmailNotConfigured, Mail
from tests.api_helpers import D1, D2, seed_world
from tests.conftest import DbCall
from tests.email_helpers import RECIPIENTS, FakeSender, set_contacts

PASSWORD = "app-password-1234"


@pytest.fixture
def preview_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(smtp, "PREVIEW_DIR", tmp_path)
    return tmp_path


def smtp_settings(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "smtp_host": "smtp.example.org",
        "smtp_port": 465,
        "smtp_user": "me@example.org",
        "smtp_app_password": PASSWORD,
        "email_from_name": "AnswerWatch",
        "dashboard_url": "https://dash.example.org",
        "timezone": "Europe/Helsinki",
    }
    return SimpleNamespace(**{**values, **overrides})


async def logs(session: AsyncSession) -> list[EmailLog]:
    return list((await session.scalars(select(EmailLog).order_by(EmailLog.created_at))).all())


def world(db: DbCall, emails: list[str] | None = None, enabled: bool = True) -> None:
    db(seed_world)
    db(lambda s: set_contacts(s, RECIPIENTS if emails is None else emails, enabled))


# ---- SMTP settings ----------------------------------------------------------------------------


@pytest.mark.parametrize(("port", "use_tls", "start_tls"), [(465, True, False), (587, False, True)])
async def test_port_decides_between_ssl_and_starttls(
    monkeypatch: pytest.MonkeyPatch, port: int, use_tls: bool, start_tls: bool
) -> None:
    seen: dict[str, Any] = {}

    async def fake_send(message: Any, **kwargs: Any) -> None:
        seen.update(kwargs, message=message)

    monkeypatch.setattr(smtp, "get_settings", lambda: smtp_settings(smtp_port=port))
    monkeypatch.setattr(smtp.aiosmtplib, "send", fake_send)
    await smtp.send_mail(["a@example.org"], Mail("Subject", "plain text", "<p>html</p>"))

    assert seen["use_tls"] is use_tls and seen["start_tls"] is start_tls
    assert seen["hostname"] == "smtp.example.org" and seen["password"] == PASSWORD
    message = seen["message"]
    assert message["Subject"] == "Subject" and message["To"] == "a@example.org"
    assert "AnswerWatch" in message["From"] and "me@example.org" in message["From"]
    kinds = [part.get_content_type() for part in message.iter_parts()]
    assert kinds == ["text/plain", "text/html"]


async def test_sending_without_credentials_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtp, "get_settings", lambda: smtp_settings(smtp_app_password=""))
    with pytest.raises(EmailNotConfigured, match="SMTP_APP_PASSWORD"):
        await smtp.send_mail(["a@example.org"], Mail("s", "t", "<p>h</p>"))


def test_error_text_never_contains_the_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtp, "get_settings", lambda: smtp_settings())
    text = smtp.error_text(RuntimeError(f"535 login failed for password {PASSWORD}"))
    assert PASSWORD not in text and "***" in text and text.startswith("RuntimeError")


# ---- the log ----------------------------------------------------------------------------------


def test_a_sent_mail_is_logged(db: DbCall) -> None:
    world(db)
    sender = FakeSender()

    async def go(s: AsyncSession) -> Any:
        company = await s.get(Company, "kemira")
        assert company is not None
        result = await smtp.deliver(s, company, "test", Mail("Hello", "t", "<p>h</p>"), sender)
        return result, await logs(s)

    result, rows = db(go)
    assert result.status == "sent" and sender.sent[0][0] == RECIPIENTS
    assert [(r.kind, r.status, r.subject, r.recipients) for r in rows] == [
        ("test", "sent", "Hello", RECIPIENTS)
    ]
    assert rows[0].sent_at is not None and rows[0].error is None


def test_a_failed_send_is_logged_and_does_not_raise(
    db: DbCall, monkeypatch: pytest.MonkeyPatch
) -> None:
    world(db)
    monkeypatch.setattr(smtp, "get_settings", lambda: smtp_settings())
    sender = FakeSender()
    sender.error = ConnectionError(f"cannot log in with {PASSWORD}")

    async def go(s: AsyncSession) -> Any:
        company = await s.get(Company, "kemira")
        assert company is not None
        result = await smtp.deliver(s, company, "alert", Mail("Hello", "t", "<p>h</p>"), sender)
        return result, await logs(s)

    result, rows = db(go)
    assert result.status == "failed" and rows[0].status == "failed" and rows[0].sent_at is None
    assert "ConnectionError" in (rows[0].error or "") and PASSWORD not in (rows[0].error or "")


def test_no_recipients_gives_a_skipped_row(db: DbCall) -> None:
    world(db, emails=[])
    sender = FakeSender()

    async def go(s: AsyncSession) -> Any:
        company = await s.get(Company, "kemira")
        assert company is not None
        result = await smtp.deliver(s, company, "test", Mail("Hello", "t", "<p>h</p>"), sender)
        return result, await logs(s)

    result, rows = db(go)
    assert result.status == "skipped" and result.detail == "no recipients"
    assert sender.sent == [] and [(r.status, r.error) for r in rows] == [
        ("skipped", "no recipients")
    ]


def test_test_email_ignores_the_emails_switch(db: DbCall) -> None:
    world(db, enabled=False)
    sender = FakeSender()

    async def go(s: AsyncSession) -> Any:
        company = await s.get(Company, "kemira")
        assert company is not None
        return await send_test_email(s, company, sender)

    assert db(go).status == "sent"
    assert sender.sent[0][1].subject == "AnswerWatch test email for Kemira"


# ---- formatting helpers -----------------------------------------------------------------------


def test_delta_has_an_explicit_sign() -> None:
    assert templates.delta_text(0.5, 0.667) == "−17 pts"
    assert templates.delta_text(0.8, 0.5) == "+30 pts"
    assert templates.delta_text(0.5, 0.501) == "no change"
    assert templates.delta_text(0.5, None) == "no earlier day"
    assert templates.percent(0.975) == "98%" and templates.percent(None) == "–"


# ---- the daily report -------------------------------------------------------------------------


async def collect(s: AsyncSession, mode: str = "live", today: date = D2) -> report.ReportData:
    company = await s.get(Company, "kemira")
    assert company is not None
    return await report.collect_report(s, company, mode, today)


def test_report_data_comes_from_live_runs_only(db: DbCall) -> None:
    world(db)
    data = db(collect)

    assert data.run_date == D2 and data.notes == ["a warning"]  # the run's own warning
    lines = {e.engine: e for e in data.engines}
    assert set(lines) == {"groq_web", "rag"}  # the dev run's gemini_memory is not here
    assert lines["groq_web"].accuracy == 0.5 and lines["groq_web"].previous == pytest.approx(0.667)
    assert lines["rag"].accuracy == 1.0
    assert data.wrong_count == 1  # groq_web Q01 on D2
    assert [(w.engine, w.code, w.explanation) for w in data.why] == [
        ("groq_web", "Q01", "The page says Espoo.")
    ]
    assert (data.alerts_warning, data.alerts_info) == (1, 0)
    assert data.events_count == 0 and data.new_public_questions == 0 and data.faq_drafts == 0


def test_report_says_when_there_is_no_run_today(db: DbCall) -> None:
    world(db)
    data = db(lambda s: collect(s, today=date(2026, 10, 25)))
    assert data.notes == ["There is no Ax run for today, so these are the latest numbers we have."]
    assert data.run_date == D2


def test_report_without_any_data(db: DbCall) -> None:
    from tests.kb_helpers import import_kemira

    db(import_kemira)
    data = db(collect)
    assert data.run_date is None and data.engines == []
    assert "No accuracy has been calculated yet." in data.notes
    mail = report.render_report(data)
    assert "no data" in mail.subject and "Open the dashboard" in mail.html


def test_rendered_report_has_text_and_html(db: DbCall, monkeypatch: pytest.MonkeyPatch) -> None:
    world(db)
    monkeypatch.setattr(report, "get_settings", lambda: smtp_settings())
    mail = report.render_report(db(collect))

    assert mail.subject == "AnswerWatch daily report: Kemira, 2026-10-21"
    for text in (mail.text, mail.html):
        assert "50%" in text and "100%" in text and "The page says Espoo." in text
        assert "−17 pts" in text and "ikely cause" in text
    assert "https://dash.example.org" in mail.text and "https://dash.example.org" in mail.html
    assert "12%" not in mail.html  # the dev run's 0.123 must never appear
    assert mail.html.startswith("<!doctype html>") and "<script" not in mail.html


def test_report_email_shows_the_competitor_reports(
    db: DbCall, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.db.models import CompetitorEvent

    ids = db(seed_world)
    db(lambda s: set_contacts(s, RECIPIENTS))

    async def add_event(session: AsyncSession) -> None:
        session.add(
            CompetitorEvent(
                company_id="kemira",
                run_date=D2,
                answer_id=ids["a2"],
                question_id=ids["q"]["Q01"],
                engine="groq_web",
                kind="company_missing",
                competitors=[{"name": "Ecolab", "rank": 1}],
                status="analysed",
                report_status="found",
                report="The cited trade article lists Ecolab only.",
            )
        )
        await session.commit()

    db(add_event)
    monkeypatch.setattr(report, "get_settings", lambda: smtp_settings())
    data = db(collect)
    assert data.events_count == 1
    mail = report.render_report(data)
    for text in (mail.text, mail.html):
        assert "The cited trade article lists Ecolab only." in text


def test_text_from_the_data_is_escaped_in_html(db: DbCall) -> None:
    data = report.ReportData("A <b>Co</b>", D2, "live", "https://x.example.org")
    data.notes = ["<script>alert(1)</script>"]
    html = report.render_html(data)
    assert "<script>" not in html and "&lt;script&gt;" in html and "A &lt;b&gt;Co" in html


def test_report_is_sent_once_a_day(db: DbCall) -> None:
    world(db)
    sender = FakeSender()

    async def send(s: AsyncSession, force: bool = False) -> report.EmailResult:
        company = await s.get(Company, "kemira")
        assert company is not None
        return await report.send_report(
            s, company, mode="live", today=_today(), force=force, sender=sender
        )

    first = db(send)
    second = db(send)
    forced = db(lambda s: send(s, True))

    assert (first.status, second.status, forced.status) == ("sent", "skipped", "sent")
    assert "already sent" in second.detail and "--force" in second.detail
    assert len(sender.sent) == 2
    rows = db(logs)
    assert [r.kind for r in rows] == ["daily_report", "daily_report"]  # skip leaves no row


def _today() -> date:
    from app.api.deps import get_today

    return get_today()


def test_report_is_not_sent_when_emails_are_off(db: DbCall) -> None:
    world(db, enabled=False)
    sender = FakeSender()

    async def go(s: AsyncSession) -> report.EmailResult:
        company = await s.get(Company, "kemira")
        assert company is not None
        return await report.send_report(s, company, mode="live", today=D2, sender=sender)

    result = db(go)
    assert result.status == "skipped" and "switched off" in result.detail
    assert sender.sent == [] and db(logs) == []


def test_dev_mode_writes_a_preview_and_sends_nothing(db: DbCall, preview_dir: Path) -> None:
    world(db)
    sender = FakeSender()

    async def go(s: AsyncSession) -> report.EmailResult:
        company = await s.get(Company, "kemira")
        assert company is not None
        return await report.send_report(s, company, mode="dev", today=D2, sender=sender)

    result = db(go)
    path = preview_dir / "email-preview-2026-10-21.html"
    assert result.status == "preview" and result.detail == str(path)
    html = path.read_text(encoding="utf-8")
    assert "[DEV] AnswerWatch daily report" in html and "12%" in html  # dev data, 0.123
    assert sender.sent == [] and db(logs) == []


# ---- the alert email --------------------------------------------------------------------------


async def run_alerts(s: AsyncSession, sender: FakeSender, mode: str = "live") -> alert.EmailResult:
    company = await s.get(Company, "kemira")
    assert company is not None
    return await alert.send_alerts(s, company, mode=mode, today=D2, sender=sender)


async def emailed_flags(s: AsyncSession) -> list[bool]:
    return [a.emailed for a in (await s.scalars(select(Alert))).all()]


def test_alert_email_lists_the_new_warning_and_marks_it(db: DbCall) -> None:
    world(db)
    sender = FakeSender()

    result = db(lambda s: run_alerts(s, sender))

    assert result.status == "sent" and len(sender.sent) == 1
    mail = sender.sent[0][1]
    assert mail.subject == "AnswerWatch alert: 1 change for Kemira"
    for body in (mail.text, mail.html):
        assert "groq_web" in body and "Q01" in body and "answer got worse" in body
        assert "/accuracy?engine=groq_web&" in body.replace("&amp;", "&")
    assert db(emailed_flags) == [True]
    assert [r.kind for r in db(logs)] == ["alert"]


def test_an_alert_is_never_emailed_twice(db: DbCall) -> None:
    world(db)
    sender = FakeSender()
    db(lambda s: run_alerts(s, sender))

    again = db(lambda s: run_alerts(s, sender))

    assert again.status == "skipped" and again.detail == "no new alerts"
    assert len(sender.sent) == 1 and len(db(logs)) == 1


def test_info_alerts_are_not_emailed(db: DbCall) -> None:
    world(db)

    async def make_info(s: AsyncSession) -> None:
        alert_row = (await s.scalars(select(Alert))).one()
        alert_row.severity, alert_row.kind = "info", "score_improved"
        await s.commit()

    db(make_info)
    sender = FakeSender()
    assert db(lambda s: run_alerts(s, sender)).detail == "no new alerts" and sender.sent == []


def test_a_failed_alert_email_is_tried_again_next_time(db: DbCall) -> None:
    world(db)
    sender = FakeSender()
    sender.error = ConnectionError("down")
    assert db(lambda s: run_alerts(s, sender)).status == "failed"
    assert db(emailed_flags) == [False]

    sender.error = None
    assert db(lambda s: run_alerts(s, sender)).status == "sent"
    assert db(emailed_flags) == [True]


def test_alerts_stay_unsent_without_recipients(db: DbCall) -> None:
    world(db, emails=[])
    sender = FakeSender()
    assert db(lambda s: run_alerts(s, sender)).detail == "no recipients"
    assert db(emailed_flags) == [False] and sender.sent == []


def test_alert_emails_respect_the_emails_switch(db: DbCall) -> None:
    world(db, enabled=False)
    sender = FakeSender()
    assert db(lambda s: run_alerts(s, sender)).status == "skipped"
    assert db(emailed_flags) == [False] and sender.sent == []


def test_dev_alert_preview_does_not_mark_alerts(db: DbCall, preview_dir: Path) -> None:
    world(db)
    sender = FakeSender()
    result = db(lambda s: run_alerts(s, sender, "dev"))
    assert result.status == "preview" and sender.sent == []
    assert (preview_dir / "email-preview-alerts-2026-10-21.html").exists()
    assert db(emailed_flags) == [False]


def test_alert_dates_are_not_limited_to_today(db: DbCall) -> None:
    """An unsent warning from an earlier day is still sent (nothing is lost if a send failed)."""
    world(db)

    async def move_back(s: AsyncSession) -> None:
        (await s.scalars(select(Alert))).one().run_date = D1
        await s.commit()

    db(move_back)
    sender = FakeSender()
    assert db(lambda s: run_alerts(s, sender)).status == "sent"
