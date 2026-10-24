"""Polite fetcher (SPEC section 1, rule 7): robots.txt, 1 request/second/domain, text only.

Results are stored in `pages`. Cache rules: an `ok` page (or a non-HTML page, or a 404/410)
younger than PAGE_CACHE_DAYS is served from the table. 403/429/5xx, network errors and robots
blocks are never cached. A temporary failure never overwrites an earlier good copy of a page.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Page
from app.fetch.extract import extract

MAX_REDIRECTS = 5
MAX_ATTEMPTS = 3  # first try + 2 retries on 5xx or network errors
MAX_BYTES = 5_000_000
MIN_SECONDS_PER_DOMAIN = 1.0
PERMANENT_GONE = (404, 410)
REDIRECTS = (301, 302, 303, 307, 308)

Sleep = Callable[[float], Awaitable[None]]


@dataclass
class FetchResult:
    url: str
    status: str  # ok | blocked_by_robots | skipped_non_html | http_error | fetch_error
    final_url: str | None = None
    http_status: int | None = None
    title: str | None = None
    h1: str | None = None
    text: str | None = None
    published_date: date | None = None
    date_kind: str | None = None
    fetched_at: datetime | None = None
    from_cache: bool = False
    error: str | None = None
    # Elements with class "question" (FAQ agent). Not stored in `pages`, so only a fresh download
    # (force=True) has them.
    questions: list[str] = field(default_factory=list)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _origin(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}"


def _allow_all() -> RobotFileParser:
    parser = RobotFileParser()
    parser.parse([])
    return parser


class PoliteFetcher:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        user_agent = get_settings().fetch_user_agent
        self._client = client or httpx.AsyncClient(timeout=20, headers={"User-Agent": user_agent})
        self._owns_client = client is None
        self._user_agent = user_agent
        self._sleep = sleep
        self._clock = clock
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}  # None = blocked for this run

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ---- network -----------------------------------------------------------------------------

    async def _throttle(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last_request.get(host, float("-inf")) + MIN_SECONDS_PER_DOMAIN
            wait -= self._clock()
            if wait > 0:
                await self._sleep(wait)
            self._last_request[host] = self._clock()

    async def _get(self, url: str) -> httpx.Response:
        """One GET (no redirects) with retries on 5xx and network errors."""
        for attempt in range(MAX_ATTEMPTS):
            last = attempt == MAX_ATTEMPTS - 1
            await self._throttle(_host(url))
            try:
                response = await self._client.get(
                    url, headers={"User-Agent": self._user_agent}, follow_redirects=False
                )
            except httpx.TransportError:
                if last:
                    raise
            else:
                if response.status_code < 500 or last:
                    return response
            await self._sleep(2.0**attempt)
        raise AssertionError("unreachable")

    async def _robots_for(self, url: str) -> RobotFileParser | None:
        origin = _origin(url)
        if origin not in self._robots:
            self._robots[origin] = await self._load_robots(origin)
        return self._robots[origin]

    async def _load_robots(self, origin: str) -> RobotFileParser | None:
        """Parsed rules, allow-all if robots.txt is absent, None (blocked) if unreachable."""
        target = f"{origin}/robots.txt"
        try:
            for _ in range(MAX_REDIRECTS + 1):
                response = await self._get(target)
                location = response.headers.get("location")
                if response.status_code not in REDIRECTS or not location:
                    break
                target = urljoin(target, location)
            else:
                return None
        except httpx.TransportError:
            return None
        code = response.status_code
        if code == 200:
            parser = RobotFileParser()
            parser.parse(response.text.splitlines())
            return parser
        if code in (401, 403, 429) or code >= 500:
            return None
        return _allow_all()

    async def _allowed(self, url: str) -> bool:
        parser = await self._robots_for(url)
        return parser is not None and parser.can_fetch(self._user_agent, url)

    async def _download(self, url: str) -> FetchResult:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            if not await self._allowed(current):
                return FetchResult(url, "blocked_by_robots", final_url=current)
            response = await self._get(current)
            location = response.headers.get("location")
            if response.status_code in REDIRECTS and location:
                current = urljoin(current, location).split("#")[0]
                continue
            return self._to_result(url, current, response)
        return FetchResult(url, "fetch_error", final_url=current, error="too many redirects")

    def _to_result(self, url: str, final_url: str, response: httpx.Response) -> FetchResult:
        code = response.status_code
        base: dict[str, Any] = {"url": url, "final_url": final_url, "http_status": code}
        if code >= 400 or code < 200:
            return FetchResult(status="http_error", **base)
        kind = response.headers.get("content-type", "text/html").lower()
        if "html" not in kind or len(response.content) > MAX_BYTES:
            return FetchResult(status="skipped_non_html", **base)
        page = extract(response.text, response.headers.get("last-modified"))
        return FetchResult(
            status="ok",
            title=page.title,
            h1=page.h1,
            text=page.text,
            published_date=page.published_date,
            date_kind=page.date_kind,
            questions=page.questions,
            **base,
        )

    # ---- database ----------------------------------------------------------------------------

    @staticmethod
    def _is_cacheable(row: Page) -> bool:
        if row.status in ("ok", "skipped_non_html"):
            return True
        return row.status == "http_error" and row.http_status in PERMANENT_GONE

    @staticmethod
    def _from_row(row: Page) -> FetchResult:
        return FetchResult(
            url=row.url,
            status=row.status,
            final_url=row.final_url,
            http_status=row.http_status,
            title=row.title,
            h1=row.h1,
            text=row.text,
            published_date=row.published_date,
            date_kind=row.date_kind,
            fetched_at=row.fetched_at,
            from_cache=True,
        )

    async def _cached(self, session: AsyncSession, url: str) -> FetchResult | None:
        row = await session.scalar(select(Page).where(Page.url == url))
        if row is None or row.fetched_at is None or not self._is_cacheable(row):
            return None
        oldest = datetime.now(UTC) - timedelta(days=get_settings().page_cache_days)
        return self._from_row(row) if row.fetched_at >= oldest else None

    async def _store(self, session: AsyncSession, result: FetchResult) -> None:
        temporary_failure = result.status != "ok" and result.http_status not in PERMANENT_GONE
        if temporary_failure:
            old = await session.scalar(select(Page.status).where(Page.url == result.url))
            if old == "ok":
                return  # keep the last good copy
        result.fetched_at = datetime.now(UTC)
        values = {
            "url": result.url,
            "final_url": result.final_url,
            "domain": _host(result.final_url or result.url),
            "title": result.title,
            "h1": result.h1,
            "text": result.text,
            "published_date": result.published_date,
            "date_kind": result.date_kind,
            "status": result.status,
            "http_status": result.http_status,
            "fetched_at": result.fetched_at,
        }
        stmt = insert(Page).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Page.url], set_={k: v for k, v in values.items() if k != "url"}
        )
        await session.execute(stmt)
        await session.commit()

    # ---- public ------------------------------------------------------------------------------

    async def fetch(self, session: AsyncSession, url: str, *, force: bool = False) -> FetchResult:
        url = url.strip().split("#")[0]
        if not force and (cached := await self._cached(session, url)):
            return cached
        try:
            result = await self._download(url)
        except httpx.HTTPError as exc:
            result = FetchResult(url, "fetch_error", error=f"{type(exc).__name__}: {exc}"[:200])
        await self._store(session, result)
        return result
