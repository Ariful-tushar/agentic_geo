"""Tested engine `gemini_memory`: plain Gemini generation, no tools, so no citations."""

import time
from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings
from app.schemas.agents import EngineAnswer


def parse_gemini_response(raw: dict[str, Any], model: str, latency_ms: int) -> EngineAnswer:
    parts = ((raw.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text") or "" for p in parts if not p.get("thought")).strip()
    usage = raw.get("usage_metadata") or {}
    return EngineAnswer(
        text=text,
        model=model,
        tokens_in=usage.get("prompt_token_count"),
        tokens_out=usage.get("candidates_token_count"),
        latency_ms=latency_ms,
        raw_json=raw,
    )


def gemini_client() -> genai.Client:
    """One attempt per SDK call: our own retry layer (limits.py) does the retrying."""
    options = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
    return genai.Client(api_key=get_settings().gemini_api_key, http_options=options)


async def ask_gemini(model: str, question: str) -> EngineAnswer:
    started = time.monotonic()
    response = await gemini_client().aio.models.generate_content(model=model, contents=question)
    latency = int((time.monotonic() - started) * 1000)
    return parse_gemini_response(response.model_dump(mode="json"), model, latency)
