"""Plain-text extract of a Wikipedia page by title.

Checked against https://www.mediawiki.org/wiki/Extension:TextExtracts (prop=extracts, explaintext,
exsectionformat) and the Wikimedia User-Agent policy: a descriptive agent with contact details,
`<client>/<version> (<url>; <email>)`. Generic or contact-less agents get HTTP 403.
"""

import logging
import re
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

API_URL = "https://en.wikipedia.org/w/api.php"
CLIENT = "AnswerWatch/0.1"
_PLACEHOLDER_REPO = "your-user/"
_CONTACT = re.compile(r"[^\s()@;]+@[^\s()@;]+\.[^\s()@;]+|https?://[^\s()]+")


def contact_from(*candidates: str) -> str | None:
    """The first real email address or URL in the candidates (placeholders are ignored)."""
    for text in candidates:
        found = _CONTACT.search(text or "")
        if found:
            return found.group(0).lstrip("+")
    return None


def user_agent() -> str:
    """`AnswerWatch/0.1 (https://github.com/<repo>; <contact>)`, built from settings only."""
    settings = get_settings()
    repo = settings.github_repo.strip()
    parts = []
    if repo and not repo.startswith(_PLACEHOLDER_REPO):
        parts.append(f"https://github.com/{repo}")
    contact = contact_from(settings.wikipedia_contact, settings.fetch_user_agent)
    if contact:
        parts.append(contact)
    else:
        log.warning("Wikimedia requires contact details: set WIKIPEDIA_CONTACT in .env")
    return f"{CLIENT} ({'; '.join(parts)})" if parts else CLIENT


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
    headers = {"User-Agent": user_agent()}
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=20, headers=headers)
    try:
        response = await client.get(API_URL, params=_params(title), headers=headers)
        response.raise_for_status()
        return parse_extract(response.json())
    finally:
        if owns_client:
            await client.aclose()
