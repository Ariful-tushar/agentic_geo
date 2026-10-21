"""The alert email (SPEC 8.6): one email with every `warning` alert that was never emailed.

An alert is emailed once: after a successful send it is marked `emailed` and never sent again.
A failed or skipped send (no recipients) leaves the alerts unmarked, so a later run tries again.
Dev mode: nothing is sent or marked; the HTML goes to logs/email-preview-alerts-<date>.html.
"""

from dataclasses import dataclass
from datetime import date
from html import escape
from urllib.parse import urlencode

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import repo
from app.db.models import Alert, Company
from app.emails import templates as t
from app.emails.smtp import EmailResult, Mail, Sender, deliver, send_mail, write_preview

KIND_TEXT = {
    "score_drop": "answer got worse",
    "company_dropped": "company no longer named",
    "competitor_overtook": "a competitor overtook the company",
    "score_improved": "answer got better",
}


@dataclass
class AlertLine:
    run_date: date
    kind: str
    engine: str
    code: str
    summary: str
    link: str


def answer_link(alert: Alert) -> str:
    """The Accuracy page with the answer panel open (the answer after the change)."""
    base = get_settings().dashboard_url.rstrip("/")
    if alert.after_answer_id is None:
        return f"{base}/alerts"
    query = urlencode({"engine": alert.engine, "answer": str(alert.after_answer_id)})
    return f"{base}/accuracy?{query}"


def alert_subject(company_name: str, count: int) -> str:
    noun = "change" if count == 1 else "changes"
    return f"AnswerWatch alert: {count} {noun} for {company_name}"


def render_alert_mail(company_name: str, lines: list[AlertLine]) -> Mail:
    subject = alert_subject(company_name, len(lines))
    dashboard = get_settings().dashboard_url
    text = [subject, ""]
    for line in lines:
        text.append(
            f"- {line.run_date.isoformat()} {line.engine}, {line.code} "
            f"({KIND_TEXT.get(line.kind, line.kind)}): {line.summary}\n  {line.link}"
        )
    text += ["", f"All alerts: {dashboard.rstrip('/')}/alerts", "", t.DISCLAIMER]

    rows = [
        [
            escape(line.run_date.isoformat()),
            f"{escape(line.engine)}<br>{escape(line.code)}",
            f"<strong>{escape(KIND_TEXT.get(line.kind, line.kind))}</strong><br>"
            f"{escape(line.summary)}"
            f'<br><a href="{escape(line.link, quote=True)}" style="color:{t.ACCENT}">'
            "See the answer</a>",
        ]
        for line in lines
    ]
    body = (
        t.heading(f"Alerts for {company_name}")
        + t.paragraph("These changes were found in the latest daily run.", muted=True)
        + t.table(["Date", "Engine, question", "What changed"], rows)
        + t.button(f"{dashboard.rstrip('/')}/alerts", "Open all alerts")
    )
    return Mail(subject, "\n".join(text), t.page(subject, body, preheader=lines[0].summary))


async def send_alerts(
    session: AsyncSession,
    company: Company,
    *,
    mode: str,
    today: date,
    sender: Sender = send_mail,
) -> EmailResult:
    if not company.emails_enabled and mode == "live":
        return EmailResult("skipped", "emails are switched off for this company")
    pending = await repo.unsent_warning_alerts(session, company.id)
    if not pending:
        return EmailResult("skipped", "no new alerts")
    lines = [
        AlertLine(a.run_date, a.kind, a.engine, q.code, a.summary, answer_link(a))
        for a, q in pending
    ]
    mail = render_alert_mail(company.name, lines)
    if mode == "dev":
        path = write_preview(mail, f"email-preview-alerts-{today.isoformat()}")
        return EmailResult("preview", str(path))
    result = await deliver(session, company, "alert", mail, sender)
    if result.status == "sent":
        for alert, _ in pending:
            alert.emailed = True
        await session.commit()
    return result
