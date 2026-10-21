"""Command line entry point: python -m app.cli <command>."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from app.db.session import get_engine, get_sessionmaker
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
