"""llm_cache: only for our own AI roles and embeddings, never for tested engines (SPEC 7.3)."""

from typing import Any

from sqlalchemy.dialects.postgresql import insert

from app.db.models import LlmCache
from app.db.session import get_sessionmaker


def is_cacheable(payload: Any) -> bool:
    """Empty answers are never cached (errors raise before reaching the cache)."""
    return bool(payload)


async def cache_get(key: str) -> dict[str, Any] | None:
    async with get_sessionmaker()() as session:
        row = await session.get(LlmCache, key)
        return row.response_json if row else None


async def cache_set(key: str, provider: str, model: str, payload: dict[str, Any]) -> None:
    if not is_cacheable(payload):
        return
    stmt = (
        insert(LlmCache)
        .values(prompt_hash=key, provider=provider, model=model, response_json=payload)
        .on_conflict_do_nothing()
    )
    async with get_sessionmaker()() as session:
        await session.execute(stmt)
        await session.commit()
