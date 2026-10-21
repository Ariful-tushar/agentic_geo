import logging
from types import SimpleNamespace

import httpx
import pytest

from app.fetch import wikipedia
from app.fetch.wikipedia import get_extract, parse_extract, user_agent


def test_parse_extract_formatversion_2() -> None:
    data = {"query": {"pages": [{"title": "Kemira", "extract": " Kemira is a company. "}]}}
    assert parse_extract(data) == "Kemira is a company."


def test_parse_extract_formatversion_1_shape() -> None:
    data = {"query": {"pages": {"123": {"title": "Kemira", "extract": "Text"}}}}
    assert parse_extract(data) == "Text"


def test_missing_page_is_none() -> None:
    assert parse_extract({"query": {"pages": [{"title": "Nope", "missing": True}]}}) is None
    assert parse_extract({}) is None


async def test_get_extract_sends_expected_query_and_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with_settings(monkeypatch, wikipedia_contact="me@example.org")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"query": {"pages": [{"extract": "Hello"}]}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await get_extract("Kemira", client) == "Hello"
    params = seen[0].url.params
    assert params["titles"] == "Kemira"
    assert params["prop"] == "extracts"
    assert params["explaintext"] == "1"
    assert params["redirects"] == "1"
    assert seen[0].headers["user-agent"].startswith("AnswerWatch/0.1 (")


async def test_get_extract_raises_on_http_error() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(httpx.HTTPStatusError):
        await get_extract("Kemira", client)


def with_settings(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    base = {"github_repo": "me/answerwatch", "wikipedia_contact": "", "fetch_user_agent": ""}
    monkeypatch.setattr(wikipedia, "get_settings", lambda: SimpleNamespace(**(base | values)))


def test_user_agent_follows_the_wikimedia_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    with_settings(monkeypatch, wikipedia_contact="me@example.org")
    assert user_agent() == "AnswerWatch/0.1 (https://github.com/me/answerwatch; me@example.org)"


def test_contact_falls_back_to_the_fetch_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    with_settings(monkeypatch, fetch_user_agent="AnswerWatchBot/0.1 (+mail@example.org)")
    assert user_agent().endswith("; mail@example.org)")


def test_contact_can_be_a_url(monkeypatch: pytest.MonkeyPatch) -> None:
    with_settings(monkeypatch, wikipedia_contact="https://example.org/about")
    assert user_agent().endswith("; https://example.org/about)")


def test_placeholder_contact_is_ignored_and_a_warning_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with_settings(
        monkeypatch,
        github_repo="your-user/answerwatch",
        fetch_user_agent="AnswerWatchBot/0.1 (+your-email)",
    )
    with caplog.at_level(logging.WARNING):
        assert user_agent() == "AnswerWatch/0.1"
    assert "WIKIPEDIA_CONTACT" in caplog.text


async def test_the_descriptive_agent_is_sent_on_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with_settings(monkeypatch, wikipedia_contact="me@example.org")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"query": {"pages": [{"extract": "Hello"}]}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await get_extract("Kemira", client)
    assert seen[0].headers["user-agent"] == user_agent()
    assert "me@example.org" in seen[0].headers["user-agent"]
