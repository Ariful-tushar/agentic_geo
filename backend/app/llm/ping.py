"""`ping`: one real call to every engine, every internal role and the embeddings (no cache)."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from app.config import get_settings
from app.llm.embeddings import embed_texts
from app.llm.engines import load_engines
from app.llm.internal import ROLES, structured

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
ENGINE_QUESTION = "Who is the CEO of Kemira, the water chemicals company?"


class PingReply(BaseModel):
    ok: bool
    word: str


@dataclass
class PingRow:
    kind: str
    name: str
    status: str  # OK | FAILED | disabled
    detail: str = ""


def _short(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:160]}"


async def _guard(kind: str, name: str, check: Callable[[], Awaitable[str]]) -> PingRow:
    try:
        return PingRow(kind, name, "OK", await check())
    except Exception as exc:
        return PingRow(kind, name, "FAILED", _short(exc))


async def ping_engines(save_fixture: bool) -> list[PingRow]:
    rows: list[PingRow] = []
    for engine in load_engines():
        if not engine.enabled:
            rows.append(PingRow("engine", engine.id, "disabled"))
            continue

        async def check(engine=engine) -> str:
            answer = await engine.ask(ENGINE_QUESTION)
            if save_fixture:
                FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
                path = FIXTURES_DIR / f"{engine.id}_response.json"
                path.write_text(
                    json.dumps(answer.raw_json, indent=2, ensure_ascii=False), encoding="utf-8"
                )
            return (
                f"{answer.model}; {len(answer.citations)} citations; "
                f"{answer.latency_ms} ms; {len(answer.text)} chars"
            )

        rows.append(await _guard("engine", engine.id, check))
    return rows


async def ping_internal() -> list[PingRow]:
    prompt = 'Reply with ok=true and word="pong".'
    rows = []
    for role in ROLES:

        async def check(role=role) -> str:
            reply = await structured(role, prompt, PingReply, use_cache=False)
            return f"valid reply: {reply.word!r}"

        rows.append(await _guard("internal", role, check))

    async def fallback() -> str:
        reply = await structured("judge", prompt, PingReply, mode="dev", use_cache=False)
        return f"groq-only (dev mode) reply: {reply.word!r}"

    rows.append(await _guard("internal", "dev mode (groq)", fallback))
    return rows


async def ping_embeddings() -> PingRow:
    async def check() -> str:
        vectors = await embed_texts(["ping"], "RETRIEVAL_QUERY", use_cache=False)
        size = len(vectors[0])
        norm = sum(x * x for x in vectors[0]) ** 0.5
        if size != get_settings().embedding_dim:
            raise ValueError(f"expected {get_settings().embedding_dim} numbers, got {size}")
        return f"{size} numbers, length {norm:.3f}"

    return await _guard("embeddings", get_settings().gemini_embed_model, check)


async def ping_all(save_fixture: bool = False) -> list[PingRow]:
    return [*await ping_engines(save_fixture), *await ping_internal(), await ping_embeddings()]
