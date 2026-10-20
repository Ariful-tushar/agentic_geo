"""Repository helpers: small, typed database functions used by the loader and agents."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, Competitor, KnowledgeSource, Question
from app.schemas.profile import ProfileIn

# Multi-row INSERT needs the same keys in every row, so generic questions get explicit Nones.
NO_FACT_FIELDS: dict[str, None] = dict.fromkeys(
    ("expected_answer", "expected_value", "tolerance", "unit", "expected_source_url")
)


@dataclass
class ImportResult:
    company_created: bool = False
    competitors_added: int = 0
    sources_added: int = 0
    questions_added: int = 0
    questions_kept: int = 0
    deactivated: int = 0


async def upsert_company(session: AsyncSession, profile: ProfileIn) -> bool:
    """Create or update the company row. Returns True when it was created."""
    company = await session.get(Company, profile.id)
    created = company is None
    if company is None:
        company = Company(id=profile.id, onboarding_status="pending")
        session.add(company)
    company.name = profile.name
    company.aliases = profile.aliases
    company.domains = profile.domains
    company.wikipedia_title = profile.wikipedia_title
    company.contact_emails = [str(e) for e in profile.contact_emails]
    company.faq_source_urls = [str(u) for u in profile.faq_source_urls]
    company.monitoring_enabled = profile.monitoring_enabled
    company.emails_enabled = profile.emails_enabled
    await session.flush()
    return created


async def sync_competitors(session: AsyncSession, profile: ProfileIn) -> tuple[int, int]:
    """Upsert listed competitors as active; mark unlisted ones inactive. Returns (added, off)."""
    rows = (
        await session.scalars(select(Competitor).where(Competitor.company_id == profile.id))
    ).all()
    existing = {c.name.lower(): c for c in rows}
    listed = {c.name.lower() for c in profile.competitors}
    added = 0
    for item in profile.competitors:
        row = existing.get(item.name.lower())
        if row is None:
            row = Competitor(company_id=profile.id, name=item.name)
            session.add(row)
            added += 1
        row.aliases, row.domains, row.active = item.aliases, item.domains, True
    deactivated = 0
    for key, row in existing.items():
        if key not in listed and row.active:
            row.active = False
            deactivated += 1
    await session.flush()
    return added, deactivated


async def sync_knowledge_sources(session: AsyncSession, profile: ProfileIn) -> tuple[int, int]:
    """Same rule as competitors: listed URLs active, unlisted URLs inactive."""
    rows = (
        await session.scalars(
            select(KnowledgeSource).where(KnowledgeSource.company_id == profile.id)
        )
    ).all()
    existing = {s.url: s for s in rows}
    listed = {str(u) for u in profile.knowledge_sources}
    added = 0
    for url in listed:
        row = existing.get(url)
        if row is None:
            session.add(KnowledgeSource(company_id=profile.id, url=url))
            added += 1
        else:
            row.active = True
    deactivated = 0
    for url, row in existing.items():
        if url not in listed and row.active:
            row.active = False
            deactivated += 1
    await session.flush()
    return added, deactivated


async def create_questions(session: AsyncSession, profile: ProfileIn) -> tuple[int, int]:
    """Insert questions that do not exist yet; existing codes are never changed."""
    values = [
        {
            "company_id": profile.id,
            "kind": "fact",
            "code": q.code,
            "text": q.text,
            "expected_answer": q.expected_answer,
            "expected_value": q.expected_value,
            "tolerance": q.tolerance,
            "unit": q.unit,
            "expected_source_url": str(q.expected_source_url) if q.expected_source_url else None,
        }
        for q in profile.fact_questions
    ] + [
        {
            **NO_FACT_FIELDS,
            "company_id": profile.id,
            "kind": "generic",
            "code": q.code,
            "text": q.text,
        }
        for q in profile.generic_questions
    ]
    stmt = (
        insert(Question)
        .values(values)
        .on_conflict_do_nothing(index_elements=["company_id", "code"])
        .returning(Question.id)
    )
    added = len((await session.execute(stmt)).all())
    return added, len(values) - added
