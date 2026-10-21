"""Tested engine `openrouter_memory`: OpenAI-compatible client pointed at OpenRouter."""

import time
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.schemas.agents import EngineAnswer

BASE_URL = "https://openrouter.ai/api/v1"


class NoCredit(Exception):
    """OpenRouter answered 402: the account has no credit for this model."""


def parse_openrouter_response(raw: dict[str, Any], model: str, latency_ms: int) -> EngineAnswer:
    message = raw["choices"][0]["message"]
    usage = raw.get("usage") or {}
    return EngineAnswer(
        text=(message.get("content") or "").strip(),
        model=model,
        tokens_in=usage.get("prompt_tokens"),
        tokens_out=usage.get("completion_tokens"),
        latency_ms=latency_ms,
        raw_json=raw,
    )


async def ask_openrouter(model: str, question: str) -> EngineAnswer:
    settings = get_settings()
    client = AsyncOpenAI(base_url=BASE_URL, api_key=settings.openrouter_api_key, max_retries=0)
    started = time.monotonic()
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": question}],
            max_tokens=settings.groq_max_output_tokens,
            extra_body={"reasoning": {"effort": "low"}},
        )
    except Exception as exc:
        if getattr(exc, "status_code", None) == 402:
            raise NoCredit("OpenRouter returned 402: no credit for this model") from exc
        raise
    latency = int((time.monotonic() - started) * 1000)
    return parse_openrouter_response(response.model_dump(mode="json"), model, latency)
