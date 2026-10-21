from typing import Any

import pytest
from pydantic import BaseModel

from app.llm import internal
from app.llm.internal import InternalAIError, structured
from tests.fakes import FakeHTTPError


class Reply(BaseModel):
    word: str


class FakeRunnable:
    def __init__(self, script: list[Any], prompts: list[str]) -> None:
        self.script = script
        self.prompts = prompts

    async def ainvoke(self, prompt: str) -> dict[str, Any]:
        self.prompts.append(prompt)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class FakeModel:
    def __init__(
        self,
        script: list[Any],
        prompts: list[str],
        options_log: list[tuple[str, dict]],
        provider: str,
    ) -> None:
        self.script, self.prompts = script, prompts
        self.options_log, self.provider = options_log, provider

    def with_structured_output(
        self, schema: type, include_raw: bool, **options: Any
    ) -> FakeRunnable:
        assert include_raw
        self.options_log.append((self.provider, options))
        return FakeRunnable(self.script, self.prompts)


def ok(word: str) -> dict[str, Any]:
    return {"raw": None, "parsed": Reply(word=word), "parsing_error": None}


def bad() -> dict[str, Any]:
    return {"raw": None, "parsed": None, "parsing_error": ValueError("not json")}


class Factory:
    def __init__(self, **scripts: list[Any]) -> None:
        self.scripts = scripts
        self.prompts: dict[str, list[str]] = {}
        self.used: list[str] = []
        self.options_log: list[tuple[str, dict]] = []

    def __call__(self, provider: str) -> FakeModel:
        self.used.append(provider)
        return FakeModel(
            self.scripts[provider],
            self.prompts.setdefault(provider, []),
            self.options_log,
            provider,
        )


@pytest.fixture(autouse=True)
def _fakes(no_db_logging: Any, memory_cache: Any) -> None:
    return None


async def test_live_uses_gemini_first() -> None:
    factory = Factory(gemini=[ok("a")], groq=[])
    assert (await structured("judge", "p", Reply, chat_factory=factory)).word == "a"
    assert factory.used == ["gemini"]


async def test_dev_mode_uses_groq_only() -> None:
    factory = Factory(groq=[ok("g")])
    result = await structured("judge", "p", Reply, mode="dev", chat_factory=factory)
    assert result.word == "g"
    assert factory.used == ["groq"]


async def test_daily_stop_falls_back_to_groq() -> None:
    factory = Factory(gemini=[FakeHTTPError(429, {"retry-after": "7200"})], groq=[ok("g")])
    result = await structured("rag", "p", Reply, chat_factory=factory)
    assert result.word == "g"
    assert factory.used == ["gemini", "groq"]


async def test_invalid_output_is_retried_once_with_the_error_appended() -> None:
    factory = Factory(gemini=[bad(), ok("fixed")], groq=[])
    result = await structured("extract", "p", Reply, chat_factory=factory)
    assert result.word == "fixed"
    first, second = factory.prompts["gemini"]
    assert first == "p"
    assert "not json" in second


async def test_invalid_output_twice_falls_back_then_fails() -> None:
    factory = Factory(gemini=[bad(), bad()], groq=[bad(), bad()])
    with pytest.raises(InternalAIError):
        await structured("draft", "p", Reply, chat_factory=factory)
    assert factory.used == ["gemini", "groq"]


async def test_other_errors_are_raised_not_hidden() -> None:
    factory = Factory(gemini=[FakeHTTPError(401)], groq=[ok("g")])
    with pytest.raises(FakeHTTPError):
        await structured("why", "p", Reply, chat_factory=factory)


async def test_second_identical_call_comes_from_the_cache(
    memory_cache: dict[str, Any],
) -> None:
    factory = Factory(gemini=[ok("once")], groq=[])
    first = await structured("summarise", "same prompt", Reply, chat_factory=factory)
    second = await structured("summarise", "same prompt", Reply, chat_factory=factory)
    assert first == second
    assert len(memory_cache) == 1


async def test_use_cache_false_skips_the_cache(memory_cache: dict[str, Any]) -> None:
    factory = Factory(gemini=[ok("a"), ok("b")], groq=[])
    await structured("judge", "p", Reply, use_cache=False, chat_factory=factory)
    second = await structured("judge", "p", Reply, use_cache=False, chat_factory=factory)
    assert second.word == "b"
    assert memory_cache == {}


def test_every_spec_role_exists() -> None:
    expected = {"judge", "why", "extract", "summarise", "draft", "rag", "readiness"}
    assert set(internal.ROLES) == expected


async def test_groq_uses_json_schema_mode_and_gemini_the_default() -> None:
    factory = Factory(gemini=[FakeHTTPError(429, {"retry-after": "7200"})], groq=[ok("g")])
    await structured("judge", "p", Reply, chat_factory=factory)
    assert factory.options_log == [("gemini", {}), ("groq", {"method": "json_schema"})]


async def test_a_400_from_the_provider_is_treated_as_invalid_output_and_retried() -> None:
    factory = Factory(groq=[FakeHTTPError(400), ok("second try")])
    result = await structured("rag", "p", Reply, mode="dev", chat_factory=factory)
    assert result.word == "second try"
    first, second = factory.prompts["groq"]
    assert first == "p" and "HTTP 400" in second
