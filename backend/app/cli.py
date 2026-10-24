"""Command line entry point: python -m app.cli <command>."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from app.agents.daily import daily_command
from app.db.session import get_engine, get_sessionmaker
from app.emails.commands import run_email_command
from app.jobs.registry import (
    JOBS,
    onboard_command,
    readiness_command,
    run_ax_command,
    run_competitor_command,
    run_faq_command,
)
from app.loop import run
from app.profiles.loader import ProfileError, import_profile, load_profile_file


def cmd_validate_profile(args: argparse.Namespace) -> int:
    profile = load_profile_file(args.file)
    print(
        f"OK: {profile.id} ({profile.name}): {len(profile.fact_questions)} fact questions, "
        f"{len(profile.generic_questions)} generic questions, "
        f"{len(profile.competitors)} competitors, {len(profile.knowledge_sources)} sources."
    )
    return 0


async def _import(profile_file: Path) -> int:
    profile = load_profile_file(profile_file)
    try:
        async with get_sessionmaker()() as session:
            result = await import_profile(session, profile)
    finally:
        await get_engine().dispose()
    print(
        f"{'Created' if result.company_created else 'Updated'} company '{profile.id}'. "
        f"Added: {result.questions_added} questions, {result.competitors_added} competitors, "
        f"{result.sources_added} sources. Kept unchanged: {result.questions_kept} questions. "
        f"Set inactive: {result.deactivated}."
    )
    return 0


def cmd_import_profile(args: argparse.Namespace) -> int:
    return run(_import(args.file))


async def _ping(save_fixture: bool) -> int:
    from app.llm.ping import ping_all

    try:
        rows = await ping_all(save_fixture)
    finally:
        await get_engine().dispose()
    width = max(len(r.name) for r in rows)
    for r in rows:
        print(f"{r.kind:<11} {r.name:<{width}}  {r.status:<8} {r.detail}")
    if save_fixture:
        print("Raw engine responses saved to backend/tests/fixtures/.")
    return 1 if any(r.status == "FAILED" for r in rows) else 0


def cmd_ping(args: argparse.Namespace) -> int:
    return run(_ping(args.save_fixture))


async def _fetch(url: str, force: bool) -> int:
    from app.fetch.fetcher import PoliteFetcher

    fetcher = PoliteFetcher()
    try:
        async with get_sessionmaker()() as session:
            result = await fetcher.fetch(session, url, force=force)
    finally:
        await fetcher.aclose()
        await get_engine().dispose()
    date_text = f"{result.published_date} ({result.date_kind})" if result.published_date else "none"
    print(f"URL:      {result.url}")
    print(f"Final:    {result.final_url}")
    print(f"Status:   {result.status} (HTTP {result.http_status})")
    print(f"Source:   {'cache' if result.from_cache else 'network'}")
    print(f"Title:    {result.title}")
    print(f"H1:       {result.h1}")
    print(f"Date:     {date_text}")
    print(f"Text:     {len(result.text or '')} characters")
    if result.error:
        print(f"Error:    {result.error}")
    return 0 if result.status == "ok" else 1


def cmd_fetch(args: argparse.Namespace) -> int:
    return run(_fetch(args.url, args.force))


def cmd_onboard(args: argparse.Namespace) -> int:
    return run(onboard_command(args.company, args.trigger))


async def _rag_ask(company_id: str, question: str, mode: str) -> int:
    from app.kb.retriever import KnowledgeBaseEmpty, rag_answer

    try:
        result = await rag_answer(get_engine(), company_id, question, mode=mode)  # type: ignore[arg-type]
    except KnowledgeBaseEmpty as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        await get_engine().dispose()
    print(f"Answer: {result.answer}")
    for quote in result.quotes:
        print(f'  quote: "{quote.text}"')
        print(f"         {quote.url}")
    if result.source_urls:
        print("Sources: " + ", ".join(result.source_urls))
    return 0


def cmd_rag_ask(args: argparse.Namespace) -> int:
    return run(_rag_ask(args.company, args.question, args.mode))


def cmd_run_ax(args: argparse.Namespace) -> int:
    return run(run_ax_command(args.company, args.mode, args.trigger))


def cmd_run_competitor(args: argparse.Namespace) -> int:
    return run(run_competitor_command(args.company, args.mode, args.trigger))


def cmd_run_faq(args: argparse.Namespace) -> int:
    return run(run_faq_command(args.company, args.mode, args.trigger))


def cmd_readiness(args: argparse.Namespace) -> int:
    return run(readiness_command(args.company, args.url))


def cmd_send_report(args: argparse.Namespace) -> int:
    return run(run_email_command("report", args.company, args.mode, args.force))


def cmd_send_alerts(args: argparse.Namespace) -> int:
    return run(run_email_command("alerts", args.company, args.mode, False))


def cmd_send_test_email(args: argparse.Namespace) -> int:
    return run(run_email_command("test", args.company, "live", False))


def cmd_daily(args: argparse.Namespace) -> int:
    return run(daily_command(args.company, args.trigger, args.mode, args.force))


def cmd_job(args: argparse.Namespace) -> int:
    job = JOBS[args.name]
    if not job.available:
        print(f"Job '{args.name}' is not available yet.", file=sys.stderr)
        return 2
    if job.needs_company and not args.company:
        print(f"Job '{args.name}' needs --company.", file=sys.stderr)
        return 2
    assert job.handler is not None
    return run(job.handler(args.company, args.trigger, args.mode))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="AnswerWatch commands")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate-profile", help="validate a profile YAML file")
    validate.add_argument("file", type=Path)
    validate.set_defaults(func=cmd_validate_profile)

    imp = sub.add_parser("import-profile", help="validate and create/update a profile")
    imp.add_argument("file", type=Path)
    imp.set_defaults(func=cmd_import_profile)

    fetch = sub.add_parser("fetch", help="fetch one page and print what was found")
    fetch.add_argument("url")
    fetch.add_argument("--force", action="store_true", help="ignore the page cache")
    fetch.set_defaults(func=cmd_fetch)

    onboard = sub.add_parser("onboard", help="build the knowledge base (RAG) of a company")
    onboard.add_argument("--company", required=True)
    onboard.add_argument("--trigger", choices=["manual", "schedule"], default="manual")
    onboard.set_defaults(func=cmd_onboard)

    rag = sub.add_parser("rag-ask", help="answer one question from the company's own pages")
    rag.add_argument("--company", required=True)
    rag.add_argument("--mode", choices=["live", "dev"], default="live")
    rag.add_argument("question")
    rag.set_defaults(func=cmd_rag_ask)

    ax = sub.add_parser("run-ax", help="run Ax for today (resumable)")
    ax.add_argument("--company", required=True)
    ax.add_argument("--mode", choices=["live", "dev"], default="live")
    ax.add_argument("--trigger", choices=["manual", "schedule"], default="manual")
    ax.set_defaults(func=cmd_run_ax)

    comp = sub.add_parser("run-competitor", help="analyse new competitor events (resumable)")
    comp.add_argument("--company", required=True)
    comp.add_argument("--mode", choices=["live", "dev"], default="live")
    comp.add_argument("--trigger", choices=["manual", "schedule"], default="manual")
    comp.set_defaults(func=cmd_run_competitor)

    faq = sub.add_parser("run-faq", help="collect new public questions and draft FAQ answers")
    faq.add_argument("--company", required=True)
    faq.add_argument("--mode", choices=["live", "dev"], default="live")  # dev = print only
    faq.add_argument("--trigger", choices=["manual", "schedule"], default="manual")
    faq.set_defaults(func=cmd_run_faq)

    readiness = sub.add_parser("readiness", help="check a page for AI-readiness")
    readiness.add_argument("--company", required=True)
    readiness.add_argument("url")
    readiness.set_defaults(func=cmd_readiness)

    job = sub.add_parser("job", help="run a job by name (used by the API and GitHub Actions)")
    job.add_argument("name", choices=sorted(JOBS))
    job.add_argument("--company", default=None)
    job.add_argument("--trigger", choices=["manual", "schedule"], default="manual")
    job.add_argument("--mode", choices=["live", "dev"], default="live")
    job.set_defaults(func=cmd_job)

    report = sub.add_parser("send-report", help="send the daily report email")
    report.add_argument("--company", required=True)
    report.add_argument("--mode", choices=["live", "dev"], default="live")
    report.add_argument("--force", action="store_true", help="send even if already sent today")
    report.set_defaults(func=cmd_send_report)

    alerts = sub.add_parser("send-alerts", help="email the new warning alerts (once each)")
    alerts.add_argument("--company", required=True)
    alerts.add_argument("--mode", choices=["live", "dev"], default="live")
    alerts.set_defaults(func=cmd_send_alerts)

    test = sub.add_parser("send-test-email", help="send a test email to the contact emails")
    test.add_argument("--company", required=True)
    test.set_defaults(func=cmd_send_test_email)

    daily = sub.add_parser("daily", help="Ax, competitor, FAQ, alert email, daily report")
    daily.add_argument("--company", default=None, help="default: every company with monitoring on")
    daily.add_argument("--trigger", choices=["manual", "schedule"], default="manual")
    daily.add_argument("--mode", choices=["live", "dev"], default="live")
    daily.add_argument("--force", action="store_true", help="resend today's report")
    daily.set_defaults(func=cmd_daily)

    ping = sub.add_parser("ping", help="test every engine, internal role and the embeddings")
    ping.add_argument("--save-fixture", action="store_true", help="save raw responses")
    ping.set_defaults(func=cmd_ping)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ProfileError as exc:
        print(f"Profile error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
