"""HTML -> title, h1, main text and a date (metadata only, no guessing from the text)."""

import json
import re
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any

from selectolax.lexbor import LexborHTMLParser as HTMLParser

_NOISE_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"]
_BLANK_LINES = re.compile(r"\n\s*\n+")

_PUBLISHED_META = ("article:published_time", "og:article:published_time", "datePublished")
_MODIFIED_META = ("article:modified_time", "og:updated_time", "dateModified")


@dataclass
class Extracted:
    title: str | None
    h1: str | None
    text: str
    published_date: date | None
    date_kind: str | None  # "published" | "modified" | None


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _meta(tree: HTMLParser, names: tuple[str, ...]) -> date | None:
    for name in names:
        selector = ", ".join(f'meta[{attr}="{name}"]' for attr in ("property", "name", "itemprop"))
        node = tree.css_first(selector)
        if node and (found := _parse_date(node.attributes.get("content"))):
            return found
    return None


def _walk(data: Any, key: str) -> date | None:
    """Find a date under `key` anywhere in JSON-LD (handles lists and @graph)."""
    if isinstance(data, dict):
        if found := _parse_date(data.get(key)):
            return found
        return next((d for v in data.values() if (d := _walk(v, key))), None)
    if isinstance(data, list):
        return next((d for v in data if (d := _walk(v, key))), None)
    return None


def _json_ld(tree: HTMLParser, key: str) -> date | None:
    for node in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.text() or "")
        except ValueError:
            continue
        if found := _walk(data, key):
            return found
    return None


def _time_tag(tree: HTMLParser) -> date | None:
    node = tree.css_first("time[datetime]")
    return _parse_date(node.attributes.get("datetime")) if node else None


def _last_modified(header: str | None) -> date | None:
    if not header:
        return None
    try:
        return parsedate_to_datetime(header).date()
    except (TypeError, ValueError):
        return None


def find_date(tree: HTMLParser, last_modified: str | None) -> tuple[date | None, str | None]:
    published = _meta(tree, _PUBLISHED_META) or _json_ld(tree, "datePublished") or _time_tag(tree)
    if published:
        return published, "published"
    modified = (
        _meta(tree, _MODIFIED_META)
        or _json_ld(tree, "dateModified")
        or _last_modified(last_modified)
    )
    return (modified, "modified") if modified else (None, None)


def _clean(text: str | None) -> str | None:
    cleaned = " ".join((text or "").split())
    return cleaned or None


def extract(html: str, last_modified: str | None = None) -> Extracted:
    tree = HTMLParser(html)
    title = _clean(tree.css_first("title").text()) if tree.css_first("title") else None
    h1 = _clean(tree.css_first("h1").text()) if tree.css_first("h1") else None
    published, kind = find_date(tree, last_modified)

    tree.strip_tags(_NOISE_TAGS)
    root = tree.css_first("main") or tree.css_first("article") or tree.body
    raw = root.text(separator="\n", strip=True) if root else ""
    text = _BLANK_LINES.sub("\n\n", raw).strip()
    return Extracted(title=title, h1=h1, text=text, published_date=published, date_kind=kind)
