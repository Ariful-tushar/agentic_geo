"""Tested AI engines: ask(question) -> EngineAnswer. Answers are never cached (SPEC 7.1, 7.3)."""

from collections.abc import Awaitable, Callable
from functools import lru_cache

import yaml

from app.config import get_settings
from app.llm.gemini_engine import ask_gemini
from app.llm.groq_engine import ask_groq
from app.llm.limits import call_with_retries, record_tokens, wait_for_token_budget
from app.llm.openrouter_engine import ask_openrouter
from app.llm.usage import log_call
from app.schemas.agents import EngineAnswer, EngineConfig

_KEY_SETTING = {
    "groq": "groq_api_key",
    "gemini": "gemini_api_key",
    "openrouter": "openrouter_api_key",
}

Asker = Callable[[str, str, bool], Awaitable[EngineAnswer]]


class EngineError(Exception):
    """A tested engine could not give an answer (missing key, empty answer, ...)."""


async def _ask(provider: str, model: str, question: str, web_search: bool) -> EngineAnswer:
    if provider == "groq":
        return await ask_groq(model, question, web_search=web_search)
    if provider == "gemini":
        return await ask_gemini(model, question)
    if provider == "openrouter":
        return await ask_openrouter(model, question)
    raise EngineError(f"unknown provider '{provider}'")


class Engine:
    def __init__(self, config: EngineConfig, asker: Asker | None = None) -> None:
        self.config = config
        self._asker: Asker = asker or (lambda m, q, w: _ask(config.provider, m, q, w))

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def model(self) -> str:
        return getattr(get_settings(), self.config.model_env.lower())

    def has_key(self) -> bool:
        return bool(getattr(get_settings(), _KEY_SETTING[self.config.provider], ""))

    async def ask(self, question: str) -> EngineAnswer:
        """Ask with only the question text. Raises DailyStop or EngineError on failure."""
        provider, model = self.config.provider, self.model
        if not self.has_key():
            raise EngineError(f"no API key set for {provider}")
        settings = get_settings()
        if provider == "groq":
            await wait_for_token_budget(provider, settings.groq_tokens_per_minute)
        try:
            answer = await call_with_retries(
                provider, lambda: self._asker(model, question, self.config.web_search)
            )
        except Exception as exc:
            await log_call(role="engine", provider=provider, model=model, error=repr(exc))
            raise
        if provider == "groq":
            record_tokens(provider, (answer.tokens_in or 0) + (answer.tokens_out or 0))
        if not answer.text:
            await log_call(role="engine", provider=provider, model=model, error="empty answer")
            raise EngineError("the engine returned an empty answer")
        await log_call(
            role="engine",
            provider=provider,
            model=model,
            tokens_in=answer.tokens_in,
            tokens_out=answer.tokens_out,
            latency_ms=answer.latency_ms,
        )
        return answer


@lru_cache
def load_engines() -> tuple[Engine, ...]:
    data = yaml.safe_load(get_settings().engines_file.read_text(encoding="utf-8"))
    return tuple(Engine(EngineConfig(**item)) for item in data["engines"])


def enabled_engines() -> list[Engine]:
    return [e for e in load_engines() if e.enabled]
