"""Our own AI (judge, why, extract, summarise, draft, rag, readiness) via LangChain.

structured(role, prompt, schema) returns a validated Pydantic object. Live mode tries Gemini and
falls back to Groq; dev mode uses Groq only. Results are cached by provider, model, prompt, schema.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Literal

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.llm.cache import cache_get, cache_set
from app.llm.limits import RETRY_STATUSES, DailyStop, call_with_retries, status_of
from app.llm.usage import log_call, make_hash

log = logging.getLogger(__name__)

Role = Literal["judge", "why", "extract", "summarise", "draft", "rag", "readiness"]
ROLES: tuple[Role, ...] = ("judge", "why", "extract", "summarise", "draft", "rag", "readiness")
Mode = Literal["live", "dev"]

ChatFactory = Callable[[str], BaseChatModel]


class InternalAIError(Exception):
    """No provider could produce a valid answer."""


def default_chat_model(provider: str) -> BaseChatModel:
    """Our own retry layer (limits.py) does the retrying, so the SDK clients get 0 retries."""
    settings = get_settings()
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.gemini_internal_model,
            google_api_key=settings.gemini_api_key,
            max_retries=0,  # the model ignores temperature (fixed sampling defaults)
        )
    from langchain_groq import ChatGroq

    return ChatGroq(
        model=settings.groq_internal_model,
        api_key=settings.groq_api_key,
        temperature=0,
        max_retries=0,
        reasoning_effort="low",
    )


def model_name(provider: str) -> str:
    settings = get_settings()
    return settings.gemini_internal_model if provider == "gemini" else settings.groq_internal_model


def providers_for(mode: Mode) -> list[str]:
    return ["groq"] if mode == "dev" else ["gemini", "groq"]


def _cache_key(provider: str, prompt: str, schema: type[BaseModel]) -> str:
    schema_json = json.dumps(schema.model_json_schema(), sort_keys=True)
    return make_hash(provider, model_name(provider), prompt, schema_json)


def _should_fall_back(exc: Exception) -> bool:
    return isinstance(exc, DailyStop) or status_of(exc) in RETRY_STATUSES


async def _invoke[T: BaseModel](
    provider: str, role: Role, prompt: str, schema: type[T], factory: ChatFactory
) -> T:
    """One provider: ask, validate, and retry once with the validation error appended."""
    # Groq's gpt-oss sometimes skips the tool call in function-calling mode ("tool_use_failed");
    # its json_schema mode is documented for this model (console.groq.com/docs/structured-outputs).
    options = {"method": "json_schema"} if provider == "groq" else {}
    runnable = factory(provider).with_structured_output(schema, include_raw=True, **options)
    current = prompt
    for _ in range(2):
        started = time.monotonic()
        raw, parsed = None, None
        try:
            result = await call_with_retries(provider, lambda text=current: runnable.ainvoke(text))
        except Exception as exc:
            if status_of(exc) != 400:  # a 400 means the model's output was rejected: ask again
                raise
            problem = f"{type(exc).__name__}: {str(exc)[:200]}"
        else:
            raw, parsed = result.get("raw"), result.get("parsed")
            error = result.get("parsing_error")
            problem = repr(error) if error else ("empty output" if parsed is None else None)
        usage = getattr(raw, "usage_metadata", None) or {}
        await log_call(
            role=role,
            provider=provider,
            model=model_name(provider),
            prompt_hash=make_hash(current),
            tokens_in=usage.get("input_tokens"),
            tokens_out=usage.get("output_tokens"),
            latency_ms=int((time.monotonic() - started) * 1000),
            error=problem,
        )
        if problem is None:
            return schema.model_validate(parsed)
        current = f"{prompt}\n\nYour last answer was invalid ({problem}). Fix it and answer again."
    raise InternalAIError(f"{provider} gave invalid output twice for role '{role}'")


async def structured[T: BaseModel](
    role: Role,
    prompt: str,
    schema: type[T],
    *,
    mode: Mode = "live",
    use_cache: bool = True,
    chat_factory: ChatFactory = default_chat_model,
) -> T:
    last_error: Exception | None = None
    for provider in providers_for(mode):
        key = _cache_key(provider, prompt, schema)
        if use_cache and (hit := await cache_get(key)) is not None:
            await log_call(
                role=role,
                provider=provider,
                model=model_name(provider),
                prompt_hash=key,
                cached=True,
            )
            return schema.model_validate(hit)
        try:
            value = await _invoke(provider, role, prompt, schema, chat_factory)
        except Exception as exc:
            if not (_should_fall_back(exc) or isinstance(exc, InternalAIError | ValidationError)):
                raise
            log.warning("internal AI: %s failed for '%s' (%s); trying next", provider, role, exc)
            last_error = exc
            continue
        if use_cache:
            await cache_set(key, provider, model_name(provider), value.model_dump(mode="json"))
        return value
    raise InternalAIError(f"all providers failed for role '{role}': {last_error!r}")
