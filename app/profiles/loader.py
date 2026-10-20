"""YAML profile -> validated ProfileIn -> database."""

from pathlib import Path

import yaml
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repo
from app.schemas.profile import ProfileIn


class ProfileError(Exception):
    """The profile file cannot be read or fails validation. Message is user-readable."""


def parse_profile(text: str) -> ProfileIn:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ProfileError(f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ProfileError("The profile must be a YAML mapping (key: value pairs).")
    try:
        return ProfileIn.model_validate(data)
    except ValidationError as exc:
        raise ProfileError(format_errors(exc)) from exc


def load_profile_file(path: Path) -> ProfileIn:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError(f"Cannot read {path}: {exc.strerror}") from exc
    return parse_profile(text)


def format_errors(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"]) or "profile"
        lines.append(f"  - {where}: {err['msg'].removeprefix('Value error, ')}")
    return f"{len(lines)} validation error(s):\n" + "\n".join(lines)


async def import_profile(session: AsyncSession, profile: ProfileIn) -> repo.ImportResult:
    """Create or update a company. Questions are only created, never changed."""
    result = repo.ImportResult()
    result.company_created = await repo.upsert_company(session, profile)
    added, off = await repo.sync_competitors(session, profile)
    result.competitors_added, result.deactivated = added, off
    added, off = await repo.sync_knowledge_sources(session, profile)
    result.sources_added, result.deactivated = added, result.deactivated + off
    result.questions_added, result.questions_kept = await repo.create_questions(session, profile)
    await session.commit()
    return result
