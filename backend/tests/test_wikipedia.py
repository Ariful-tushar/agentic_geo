import httpx
import pytest

from app.fetch.wikipedia import get_extract, parse_extract


def test_parse_extract_formatversion_2() -> None:
    data = {"query": {"pages": [{"title": "Kemira", "extract": " Kemira is a company. "}]}}
    assert parse_extract(data) == "Kemira is a company."


def test_parse_extract_formatversion_1_shape() -> None:
    data = {"query": {"pages": {"123": {"title": "Kemira", "extract": "Text"}}}}
    assert parse_extract(data) == "Text"


def test_missing_page_is_none() -> None:
    assert parse_extract({"query": {"pages": [{"title": "Nope", "missing": True}]}}) is None
    assert parse_extract({}) is None


async def test_get_extract_sends_expected_query_and_user_agent() -> None:
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
    assert "AnswerWatchBot" in seen[0].headers["user-agent"]


async def test_get_extract_raises_on_http_error() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(httpx.HTTPStatusError):
        await get_extract("Kemira", client)
