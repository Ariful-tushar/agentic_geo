"""The daily report email (SPEC 8.6): what the numbers are today, what changed, what to look at.

`collect_report` reads the database into a plain `ReportData`; `render_report` turns it into
HTML + text; `send_report` ties them together with the sending rules:
- `emails_enabled` off -> nothing is sent;
- one report per company and day (a second call is skipped unless `force`);
- dev mode -> nothing is sent, the HTML is written to logs/email-preview-<date>.html.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import repo
from app.db.models import (
    Alert,
    Answer,
    Company,
    CompetitorEvent,
    EmailLog,
    FaqDraft,
    PublicQuestion,
    Question,
    Run,
    Score,
    WhyFinding,
)
from app.emails import templates as t
from app.emails.smtp import EmailResult, Mail, Sender, deliver, send_mail, write_preview
from app.llm.engines import load_engines

RAG_LABEL = "Our RAG on the company's own pages"
TOP_WHY = 3
NEWEST_REPORTS = 2
MAX_TEXT = 220


@dataclass
class EngineLine:
    engine: str
    label: str
    accuracy: float
    previous: float | None
    n_questions: int


@dataclass
class WhyLine:
    engine: str
    code: str
    question: str
    explanation: str
    fix: str


@dataclass
class EventLine:
    engine: str
    code: str
    kind: str
    report: str


@dataclass
class ReportData:
    company_name: str
    run_date: date | None
    mode: str
    dashboard_url: str
    engines: list[EngineLine] = field(default_factory=list)
    wrong_count: int = 0
    why: list[WhyLine] = field(default_factory=list)
    events_count: int = 0
    events: list[EventLine] = field(default_factory=list)
    alerts_warning: int = 0
    alerts_info: int = 0
    new_public_questions: int = 0
    faq_drafts: int = 0
    notes: list[str] = field(default_factory=list)


def short(text: str | None, limit: int = MAX_TEXT) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def engine_labels() -> dict[str, str]:
    labels = {engine.id: engine.config.label for engine in load_engines()}
    labels["rag"] = RAG_LABEL
    return labels


def day_bounds(day: date) -> tuple[datetime, datetime]:
    zone = ZoneInfo(get_settings().timezone)
    start = datetime.combine(day, time.min, tzinfo=zone)
    return start, datetime.combine(day, time.max, tzinfo=zone)


def as_float(value: Decimal | float) -> float:
    return float(value)


# ---- collecting -------------------------------------------------------------------------------


async def run_notes(session: AsyncSession, company_id: str, mode: str, today: date) -> list[str]:
    """Warnings about today's Ax run, so the reader knows how far to trust the numbers."""
    run = await session.scalar(
        select(Run).where(
            Run.company_id == company_id,
            Run.kind == "ax",
            Run.run_date == today,
            Run.mode == mode,
        )
    )
    if run is None:
        return ["There is no Ax run for today, so these are the latest numbers we have."]
    notes: list[str] = []
    if run.status != "completed":
        notes.append(f"Today's Ax run is {run.status}; some answers may be missing.")
    for warning in (run.details or {}).get("warnings", [])[:3]:
        notes.append(short(str(warning)))
    return notes


async def wrong_answers(
    session: AsyncSession, company_id: str, run_date: date, mode: str
) -> tuple[int, list[WhyLine]]:
    """Wrong answers of the tested engines in that day's run, and the first few why findings."""
    rows = (
        await session.execute(
            select(Answer.engine, Question.code, Question.text, WhyFinding)
            .join(Run, Run.id == Answer.run_id)
            .join(Question, Question.id == Answer.question_id)
            .join(Score, Score.answer_id == Answer.id)
            .outerjoin(WhyFinding, WhyFinding.answer_id == Answer.id)
            .where(
                Run.company_id == company_id,
                Run.kind == "ax",
                Run.run_date == run_date,
                Run.mode == mode,
                Answer.engine != "rag",
                Score.verdict == "wrong",
            )
            .order_by(Answer.engine, Question.code)
        )
    ).all()
    why = [
        WhyLine(
            engine=engine,
            code=code,
            question=text,
            explanation=short(finding.explanation),
            fix=short(finding.suggested_fix),
        )
        for engine, code, text, finding in rows
        if finding is not None and finding.explanation
    ]
    return len(rows), why[:TOP_WHY]


async def event_lines(
    session: AsyncSession, company_id: str, run_date: date, mode: str
) -> tuple[int, list[EventLine]]:
    """Competitor events of that day, and the newest ones that already have a report."""
    base = repo.live_competitor_events(company_id, mode).where(CompetitorEvent.run_date == run_date)
    count = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = (
        await session.execute(
            base.add_columns(Question.code)
            .join(Question, Question.id == CompetitorEvent.question_id)
            .where(CompetitorEvent.report.is_not(None))
            .order_by(CompetitorEvent.analysed_at.desc().nulls_last())
            .limit(NEWEST_REPORTS)
        )
    ).all()
    events = [
        EventLine(event.engine, code, event.kind, short(event.report)) for event, code in rows
    ]
    return count, events


async def alert_counts(session: AsyncSession, company_id: str, run_date: date) -> tuple[int, int]:
    rows = (
        await session.execute(
            select(Alert.severity, func.count())
            .where(Alert.company_id == company_id, Alert.run_date == run_date)
            .group_by(Alert.severity)
        )
    ).all()
    counts = dict(rows)
    return counts.get("warning", 0), counts.get("info", 0)


async def faq_counts(session: AsyncSession, company_id: str, run_date: date) -> tuple[int, int]:
    start, end = day_bounds(run_date)
    questions = await session.scalar(
        select(func.count())
        .select_from(PublicQuestion)
        .where(
            PublicQuestion.company_id == company_id,
            PublicQuestion.first_seen_at.between(start, end),
        )
    )
    drafts = await session.scalar(
        select(func.count())
        .select_from(FaqDraft)
        .where(FaqDraft.company_id == company_id, FaqDraft.created_at.between(start, end))
    )
    return questions or 0, drafts or 0


async def collect_report(
    session: AsyncSession, company: Company, mode: str, today: date
) -> ReportData:
    data = ReportData(
        company_name=company.name,
        run_date=None,
        mode=mode,
        dashboard_url=get_settings().dashboard_url,
    )
    data.notes = await run_notes(session, company.id, mode, today)
    per_engine = await repo.accuracy_latest_two(session, company.id, mode)
    if not per_engine:
        data.notes.append("No accuracy has been calculated yet.")
        return data
    labels = engine_labels()
    for engine, rows in sorted(per_engine.items()):
        previous = as_float(rows[1].accuracy) if len(rows) > 1 else None
        data.engines.append(
            EngineLine(
                engine,
                labels.get(engine, engine),
                as_float(rows[0].accuracy),
                previous,
                rows[0].n_questions,
            )
        )
    data.run_date = max(rows[0].run_date for rows in per_engine.values())
    data.wrong_count, data.why = await wrong_answers(session, company.id, data.run_date, mode)
    data.events_count, data.events = await event_lines(session, company.id, data.run_date, mode)
    data.alerts_warning, data.alerts_info = await alert_counts(session, company.id, data.run_date)
    data.new_public_questions, data.faq_drafts = await faq_counts(
        session, company.id, data.run_date
    )
    return data


# ---- rendering --------------------------------------------------------------------------------


def report_subject(data: ReportData) -> str:
    day = data.run_date.isoformat() if data.run_date else "no data"
    prefix = "[DEV] " if data.mode == "dev" else ""
    return f"{prefix}AnswerWatch daily report: {data.company_name}, {day}"


def event_kind_text(kind: str) -> str:
    return "company not mentioned" if kind == "company_missing" else "a competitor was ahead"


def summary_lines(data: ReportData) -> list[str]:
    lines = [f"Wrong answers today (tested engines): {data.wrong_count}."]
    lines.append(f"Competitor events: {data.events_count}.")
    lines.append(f"Alerts: {data.alerts_warning} warning, {data.alerts_info} info.")
    lines.append(
        f"New public questions: {data.new_public_questions}; FAQ drafts: {data.faq_drafts}."
    )
    return lines


def render_text(data: ReportData) -> str:
    out = [report_subject(data), ""]
    out += [f"Note: {note}" for note in data.notes]
    if data.notes:
        out.append("")
    if data.engines:
        out.append("Accuracy (share of fact questions answered correctly)")
        for e in data.engines:
            out.append(
                f"- {e.label}: {t.percent(e.accuracy)} ({t.delta_text(e.accuracy, e.previous)}, "
                f"{e.n_questions} questions)"
            )
        out += ["", *summary_lines(data)]
    if data.why:
        out += ["", "Why answers were wrong (likely cause, not proof):"]
        for w in data.why:
            out.append(f"- {w.engine}, {w.code}: {w.explanation} Fix: {w.fix}")
    if data.events:
        out += ["", "Newest competitor reports:"]
        for e in data.events:
            out.append(f"- {e.engine}, {e.code} ({event_kind_text(e.kind)}): {e.report}")
    out += ["", f"Dashboard: {data.dashboard_url}", "", t.DISCLAIMER]
    return "\n".join(out)


def engines_table(data: ReportData) -> str:
    rows = []
    for e in data.engines:
        change = (
            f'<span style="color:{t.delta_color(e.accuracy, e.previous)}">'
            f"{escape(t.delta_text(e.accuracy, e.previous))}</span>"
        )
        rows.append(
            [
                escape(e.label),
                f"<strong>{t.percent(e.accuracy)}</strong>",
                change,
                str(e.n_questions),
            ]
        )
    return t.table(["Engine", "Today", "Change", "Questions"], rows)


def why_block(data: ReportData) -> str:
    if not data.why:
        return ""
    items = "".join(
        f'<li style="margin:6px 0;font-size:14px;line-height:1.5"><strong>{escape(w.engine)}, '
        f"{escape(w.code)}:</strong> {escape(w.explanation)}"
        f'<br><span style="color:{t.MUTED}">Fix: {escape(w.fix)}</span></li>'
        for w in data.why
    )
    return (
        t.heading("Why answers were wrong")
        + t.paragraph("Likely cause, not proof.", muted=True)
        + f'<ul style="padding-left:20px;margin:4px 0">{items}</ul>'
    )


def events_block(data: ReportData) -> str:
    if not data.events:
        return ""
    items = "".join(
        f'<li style="margin:6px 0;font-size:14px;line-height:1.5"><strong>{escape(e.engine)}, '
        f"{escape(e.code)}</strong> ({escape(event_kind_text(e.kind))}): {escape(e.report)}</li>"
        for e in data.events
    )
    return t.heading("Newest competitor reports") + f'<ul style="padding-left:20px">{items}</ul>'


def render_html(data: ReportData) -> str:
    subject = report_subject(data)
    body = t.heading(f"Daily report: {data.company_name}")
    if data.run_date:
        body += t.paragraph(f"Data from {data.run_date.isoformat()}.", muted=True)
    for note in data.notes:
        body += (
            f'<p style="margin:8px 0;padding:8px 10px;background:#fef3c7;border-radius:6px;'
            f'font-size:14px;color:#92400e">{escape(note)}</p>'
        )
    if data.engines:
        body += t.heading("Accuracy") + t.paragraph(
            "Share of fact questions answered correctly, with the change since the day before.",
            muted=True,
        )
        body += engines_table(data)
        body += t.heading("Today in short") + "".join(t.paragraph(s) for s in summary_lines(data))
        body += why_block(data) + events_block(data)
    body += t.button(data.dashboard_url, "Open the dashboard")
    preheader = f"{data.wrong_count} wrong answers, {data.alerts_warning} warning alerts"
    return t.page(subject, body, preheader=preheader)


def render_report(data: ReportData) -> Mail:
    return Mail(report_subject(data), render_text(data), render_html(data))


# ---- sending ----------------------------------------------------------------------------------


async def already_sent_today(session: AsyncSession, company_id: str, today: date) -> bool:
    start, end = day_bounds(today)
    found = await session.scalar(
        select(EmailLog.id)
        .where(
            EmailLog.company_id == company_id,
            EmailLog.kind == "daily_report",
            EmailLog.status == "sent",
            EmailLog.sent_at.between(start, end),
        )
        .limit(1)
    )
    return found is not None


async def send_report(
    session: AsyncSession,
    company: Company,
    *,
    mode: str,
    today: date,
    force: bool = False,
    sender: Sender = send_mail,
) -> EmailResult:
    if not company.emails_enabled and mode == "live":
        return EmailResult("skipped", "emails are switched off for this company")
    data = await collect_report(session, company, mode, today)
    mail = render_report(data)
    if mode == "dev":
        path = write_preview(mail, f"email-preview-{today.isoformat()}")
        return EmailResult("preview", str(path))
    if not force and await already_sent_today(session, company.id, today):
        return EmailResult("skipped", "today's report was already sent (use --force to resend)")
    return await deliver(session, company, "daily_report", mail, sender)
