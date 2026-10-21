"""Plain-text extract of a Wikipedia page by title.

Checked against https://www.mediawiki.org/wiki/Extension:TextExtracts (prop=extracts, explaintext,
exsectionformat) and the Wikimedia User-Agent policy (descriptive agent with contact details).
"""

from typing import Any

import httpx

from app.config import get_settings

API_URL = "https://en.wikipedia.org/w/api.php"


def _params(title: str) -> dict[str, Any]:
    return {
        "action": "query",
        "prop": "extracts",
        "explaintext": 1,
        "exsectionformat": "plain",
        "redirects": 1,
        "titles": title,
        "format": "json",
        "formatversion": 2,
    }


def parse_extract(data: dict[str, Any]) -> str | None:
    """Text of the first page in the response, or None if the page is missing."""
    pages = data.get("query", {}).get("pages", [])
    if isinstance(pages, dict):  # formatversion 1 shape
        pages = list(pages.values())
    for page in pages:
        if page.get("missing") or page.get("invalid"):
            continue
        text = (page.get("extract") or "").strip()
        if text:
            return text
    return None


async def get_extract(title: str, client: httpx.AsyncClient | None = None) -> str | None:
    """Raises httpx.HTTPError on network or HTTP errors; returns None for a missing page."""
    headers = {"User-Agent": get_settings().fetch_user_agent}
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=20, headers=headers)
    try:
        response = await client.get(API_URL, params=_params(title), headers=headers)
        response.raise_for_status()
        return parse_extract(response.json())
    finally:
        if owns_client:
            await client.aclose()
