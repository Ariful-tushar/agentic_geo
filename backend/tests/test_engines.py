import json
from pathlib import Path
from typing import Any

import pytest

from app.llm import engines as engines_module
from app.llm.engines import Engine, EngineError, load_engines
from app.llm.gemini_engine import parse_gemini_response
from app.llm.groq_engine import parse_groq_response
from app.llm.openrouter_engine import parse_openrouter_response
from app.schemas.agents import EngineAnswer, EngineConfig

FIXTURES = Path(__file__).parent / "fixtures"


class FakeSettings:
    gemini_api_key = "x"
    gemini_probe_model = "probe-model"
    groq_tokens_per_minute = 8000


def test_groq_citations_come_from_text_then_visited_pages() -> None:
    raw = json.loads((FIXTURES / "groq_sample.json").read_text(encoding="utf-8"))
    answer = parse_groq_response(raw, "m", 10)
    urls = [c.url for c in answer.citations]
    assert urls[:2] == ["https://www.kemira.com/company/leadership/", "https://example.com/news"]
    assert "https://news.example.org/kemira-ceo" in urls
    assert "https://www.kemira.com/" in urls
    assert len(urls) == len(set(urls))
    assert (answer.tokens_in, answer.tokens_out) == (120, 45)


def test_saved_real_groq_response_has_citations() -> None:
    path = FIXTURES / "groq_web_response.json"
    if not path.exists():
        pytest.skip("run `ping --save-fixture` first")
    answer = parse_groq_response(json.loads(path.read_text(encoding="utf-8")), "m", 1)
    assert answer.text
    assert len(answer.citations) >= 1
    assert all(c.url.startswith("http") for c in answer.citations)


def test_groq_without_markers_or_urls_has_no_citations() -> None:
    raw = {"choices": [{"message": {"content": "Antti Salminen."}}]}
    assert parse_groq_response(raw, "m", 1).citations == []


def test_gemini_parse_skips_thought_parts() -> None:
    raw = {
        "candidates": [{"content": {"parts": [{"text": "hmm", "thought": True}, {"text": "Hi"}]}}],
        "usage_metadata": {"prompt_token_count": 3, "candidates_token_count": 1},
    }
    answer = parse_gemini_response(raw, "g", 5)
    assert answer.text == "Hi"
    assert answer.citations == []
    assert answer.tokens_in == 3


def test_openrouter_parse() -> None:
    raw = {"choices": [{"message": {"content": " Yes "}}], "usage": {"prompt_tokens": 1}}
    assert parse_openrouter_response(raw, "o", 2).text == "Yes"


def test_engines_yaml_has_three_engines_and_openrouter_disabled() -> None:
    by_id = {e.id: e for e in load_engines()}
    assert set(by_id) == {"groq_web", "gemini_memory", "openrouter_memory"}
    assert by_id["groq_web"].config.web_search is True
    assert by_id["openrouter_memory"].enabled is False


def make_engine(text: str = "answer") -> tuple[Engine, list[str]]:
    asked: list[str] = []

    async def asker(model: str, question: str, web_search: bool) -> EngineAnswer:
        asked.append(question)
        return EngineAnswer(text=text, model=model)

    config = EngineConfig(id="e", provider="gemini", model_env="gemini_probe_model", label="test")
    return Engine(config, asker), asked


@pytest.fixture
def with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engines_module, "get_settings", lambda: FakeSettings())


async def test_engine_sends_only_the_question_and_never_touches_the_cache(
    with_keys: None, no_db_logging: list[dict[str, Any]]
) -> None:
    engine, asked = make_engine()
    answer = await engine.ask("Who is the CEO?")
    assert asked == ["Who is the CEO?"]
    assert answer.model == "probe-model"
    assert no_db_logging[-1]["role"] == "engine"
    # engines.py has no cache import at all: tested-engine answers are never cached.
    assert not hasattr(engines_module, "cache_get")
    assert not hasattr(engines_module, "cache_set")


async def test_empty_answer_is_an_error(
    with_keys: None, no_db_logging: list[dict[str, Any]]
) -> None:
    engine, _ = make_engine(text="")
    with pytest.raises(EngineError, match="empty"):
        await engine.ask("q")
    assert no_db_logging[-1]["error"] == "empty answer"


async def test_missing_key_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class NoKey(FakeSettings):
        gemini_api_key = ""

    monkeypatch.setattr(engines_module, "get_settings", lambda: NoKey())
    engine, asked = make_engine()
    with pytest.raises(EngineError, match="no API key"):
        await engine.ask("q")
    assert asked == []
