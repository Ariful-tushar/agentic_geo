"""Tested engine `groq_web`: a Groq model with the browser_search tool.

Checked against https://console.groq.com/docs/browser-search and the groq 0.37 SDK types:
sources appear as inline markers like 【2†L6-L10】 in the text, and the pages visited are
listed in message.executed_tools[].search_results / browser_results.
"""

import re
import time
from typing import Any

from groq import AsyncGroq

from app.config import get_settings
from app.schemas.agents import Citation, EngineAnswer

_URL = re.compile(r"https?://[^\s<>()\[\]【】\"']+")
_MARKER = re.compile(r"【\d+†")


def _clean(url: str) -> str:
    return url.rstrip(".,;:!?")


def parse_groq_citations(message: dict[str, Any]) -> list[Citation]:
    """URLs written in the text first, then (if the text has markers) the pages visited."""
    text = message.get("content") or ""
    found: dict[str, str | None] = {_clean(u): None for u in _URL.findall(text)}
    if _MARKER.search(text) or not found:
        for tool in message.get("executed_tools") or []:
            results = (tool.get("search_results") or {}).get("results") or []
            for item in [*results, *(tool.get("browser_results") or [])]:
                url = item.get("url")
                if url and url not in found:
                    found[url] = item.get("title")
    return [Citation(url=u, title=t) for u, t in found.items()]


def parse_groq_response(raw: dict[str, Any], model: str, latency_ms: int) -> EngineAnswer:
    message = raw["choices"][0]["message"]
    usage = raw.get("usage") or {}
    return EngineAnswer(
        text=(message.get("content") or "").strip(),
        citations=parse_groq_citations(message),
        model=model,
        tokens_in=usage.get("prompt_tokens"),
        tokens_out=usage.get("completion_tokens"),
        latency_ms=latency_ms,
        raw_json=raw,
    )


async def ask_groq(model: str, question: str, *, web_search: bool) -> EngineAnswer:
    settings = get_settings()
    client = AsyncGroq(api_key=settings.groq_api_key, max_retries=0)
    extra: dict[str, Any] = {}
    if web_search:
        extra = {"tools": [{"type": "browser_search"}], "tool_choice": "required"}
    started = time.monotonic()
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": question}],
        max_completion_tokens=settings.groq_max_output_tokens,
        reasoning_effort="low",
        **extra,
    )
    latency = int((time.monotonic() - started) * 1000)
    return parse_groq_response(response.model_dump(mode="json"), model, latency)
