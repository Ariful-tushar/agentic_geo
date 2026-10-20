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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="AnswerWatch commands")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate-profile", help="validate a profile YAML file")
    validate.add_argument("file", type=Path)
    validate.set_defaults(func=cmd_validate_profile)

    imp = sub.add_parser("import-profile", help="validate and create/update a profile")
    imp.add_argument("file", type=Path)
    imp.set_defaults(func=cmd_import_profile)
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
