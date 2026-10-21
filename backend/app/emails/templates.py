"""Shared look of the emails: one HTML layout (tables and inline CSS, because mail programs
ignore stylesheets), small formatting helpers, and the test email."""

from html import escape

from app.emails.smtp import Mail

ACCENT = "#1d4ed8"
TEXT = "#111827"
MUTED = "#6b7280"
GOOD = "#15803d"
BAD = "#b91c1c"
FONT = "-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif"

DISCLAIMER = (
    "AnswerWatch tests public AI tools with the same questions every day. Results are samples "
    "and can change between runs; they are not a guarantee of what any AI will say."
)


def percent(value: float | None) -> str:
    return "–" if value is None else f"{round(value * 100)}%"


def delta_text(today: float | None, previous: float | None) -> str:
    """Change in percentage points with an explicit sign ('+3 pts', '−2 pts', 'no change')."""
    if today is None or previous is None:
        return "no earlier day"
    points = round((today - previous) * 100)
    if points == 0:
        return "no change"
    sign = "+" if points > 0 else "−"
    return f"{sign}{abs(points)} pts"


def delta_color(today: float | None, previous: float | None) -> str:
    if today is None or previous is None or round((today - previous) * 100) == 0:
        return MUTED
    return GOOD if today > previous else BAD


def heading(text: str) -> str:
    return (
        f'<h2 style="font-size:16px;margin:24px 0 8px;color:{TEXT};'
        f'border-bottom:1px solid #e5e7eb;padding-bottom:4px">{escape(text)}</h2>'
    )


def paragraph(text: str, *, muted: bool = False) -> str:
    color = MUTED if muted else TEXT
    style = f"margin:6px 0;font-size:14px;line-height:1.5;color:{color}"
    return f'<p style="{style}">{escape(text)}</p>'


def button(url: str, label: str) -> str:
    return (
        f'<p style="margin:24px 0 8px"><a href="{escape(url, quote=True)}" '
        f'style="background:{ACCENT};color:#ffffff;text-decoration:none;padding:10px 16px;'
        f'border-radius:6px;font-size:14px;display:inline-block">{escape(label)}</a></p>'
    )


def page(title: str, body: str, *, preheader: str = "") -> str:
    """The whole HTML document around a body."""
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title></head>"
        f'<body style="margin:0;background:#f3f4f6;font-family:{FONT};color:{TEXT}">'
        f'<span style="display:none;max-height:0;overflow:hidden">{escape(preheader)}</span>'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        '<td align="center" style="padding:16px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="max-width:600px;background:#ffffff;border-radius:8px">'
        f'<tr><td style="padding:20px 24px 4px;font-size:13px;font-weight:600;color:{ACCENT}">'
        "AnswerWatch</td></tr>"
        f'<tr><td style="padding:0 24px 24px">{body}'
        f'<p style="margin:24px 0 0;font-size:12px;line-height:1.4;color:{MUTED}">'
        f"{escape(DISCLAIMER)}</p></td></tr></table></td></tr></table></body></html>"
    )


def table(headers: list[str], rows: list[list[str]]) -> str:
    """A simple table; cells are already-safe HTML."""
    head = "".join(
        f'<th align="left" style="padding:6px 8px;font-size:12px;color:{MUTED};'
        f'border-bottom:1px solid #e5e7eb">{escape(h)}</th>'
        for h in headers
    )
    body = "".join(
        "<tr>"
        + "".join(
            f'<td style="padding:6px 8px;font-size:14px;border-bottom:1px solid #f3f4f6">'
            f"{cell}</td>"
            for cell in row
        )
        + "</tr>"
        for row in rows
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        f"<tr>{head}</tr>{body}</table>"
    )


def build_test_mail(company_name: str, dashboard_url: str) -> Mail:
    """The mail sent by `send-test-email`: proves SMTP and the recipient list work."""
    subject = f"AnswerWatch test email for {company_name}"
    lines = [
        f"This is a test email from AnswerWatch for {company_name}.",
        "If you can read it, sending reports and alerts works.",
    ]
    body = (
        heading("Test email")
        + "".join(paragraph(line) for line in lines)
        + button(dashboard_url, "Open the dashboard")
    )
    text = "\n".join([*lines, "", f"Dashboard: {dashboard_url}", "", DISCLAIMER])
    return Mail(subject, text, page(subject, body, preheader=lines[0]))
