"""Log every AI call in llm_calls (cost is 0 on free tiers)."""

import hashlib
import logging

from app.db.models import LlmCall
from app.db.session import get_sessionmaker

log = logging.getLogger(__name__)


def make_hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


async def log_call(
    *,
    role: str,
    provider: str,
    model: str,
    prompt_hash: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    latency_ms: int | None = None,
    cached: bool = False,
    error: str | None = None,
) -> None:
    """A logging problem must never break the AI call itself."""
    try:
        async with get_sessionmaker()() as session:
            session.add(
                LlmCall(
                    role=role,
                    provider=provider,
                    model=model,
                    prompt_hash=prompt_hash,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                    cached=cached,
                    error=error[:500] if error else None,
                )
            )
            await session.commit()
    except Exception as exc:
        log.warning("could not write llm_calls row: %s", exc)
