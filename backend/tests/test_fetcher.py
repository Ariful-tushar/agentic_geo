from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update

from app.db.models import Page
from app.fetch.fetcher import FetchResult, PoliteFetcher
from tests.conftest import DbCall

HTML = (Path(__file__).parent / "fixtures" / "sample_page.html").read_text(encoding="utf-8")
URL = "https://www.example.com/company/"
ROBOTS_OK = "User-agent: *\nDisallow: /private/\n"

Handler = Callable[[httpx.Request], httpx.Response]


class Site:
    """A fake website: routes by path, counts requests, records times."""

    def __init__(self, routes: dict[str, Handler | httpx.Response]) -> None:
        self.routes = routes
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        route = self.routes.get(request.url.path)
        if route is None:
            return httpx.Response(404)
        return route(request) if callable(route) else route

    def page_requests(self) -> list[str]:
        return [u for u in self.requests if not u.endswith("/robots.txt")]


def html_response(body: str = HTML, **headers: str) -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": "text/html", **headers})


class Clock:
    """Fake time: sleeping advances it, so throttling can be checked without waiting."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_fetcher(site: Site, clock: Clock | None = None) -> PoliteFetcher:
    clock = clock or Clock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(site))
    return PoliteFetcher(client, sleep=clock.sleep, clock=clock)


def run_fetch(
    db: DbCall, site: Site, url: str = URL, *, force: bool = False, clock: Clock | None = None
) -> FetchResult:
    async def go(session: Any) -> FetchResult:
        return await make_fetcher(site, clock).fetch(session, url, force=force)

    return db(go)


def basic_site(**extra: Handler | httpx.Response) -> Site:
    return Site(
        {"/robots.txt": httpx.Response(200, text=ROBOTS_OK), "/company/": html_response(), **extra}
    )


def page_rows(db: DbCall) -> list[Page]:
    async def go(session: Any) -> list[Page]:
        return list((await session.scalars(select(Page))).all())

    return db(go)


def test_ok_page_is_extracted_and_stored(db: DbCall) -> None:
    result = run_fetch(db, basic_site())
    assert result.status == "ok"
    assert result.title == "About us | Example Oy"
    assert not result.from_cache
    (row,) = page_rows(db)
    assert row.status == "ok"
    assert row.domain == "www.example.com"
    assert row.http_status == 200
    assert "4,900 employees" in row.text
    assert "<p>" not in row.text  # text only, never full HTML


def test_second_fetch_comes_from_the_cache(db: DbCall) -> None:
    site = basic_site()
    run_fetch(db, site)
    second = run_fetch(db, site)
    assert second.from_cache
    assert len(site.page_requests()) == 1


def test_force_bypasses_the_cache(db: DbCall) -> None:
    site = basic_site()
    run_fetch(db, site)
    run_fetch(db, site, force=True)
    assert len(site.page_requests()) == 2


def test_old_cache_entries_are_refetched(db: DbCall) -> None:
    site = basic_site()
    run_fetch(db, site)

    async def age(session: Any) -> None:
        old = datetime.now(UTC) - timedelta(days=30)
        await session.execute(update(Page).values(fetched_at=old))
        await session.commit()

    db(age)
    assert not run_fetch(db, site).from_cache


@pytest.mark.parametrize("code", [403, 429, 500, 503])
def test_these_statuses_are_never_cached(db: DbCall, code: int) -> None:
    site = basic_site(**{"/company/": httpx.Response(code)})
    first = run_fetch(db, site)
    assert (first.status, first.http_status) == ("http_error", code)
    before = len(site.page_requests())
    second = run_fetch(db, site)
    assert not second.from_cache
    assert len(site.page_requests()) > before


def test_404_is_cached(db: DbCall) -> None:
    site = basic_site(**{"/company/": httpx.Response(404)})
    run_fetch(db, site)
    assert run_fetch(db, site).from_cache


def test_temporary_failure_keeps_the_last_good_copy(db: DbCall) -> None:
    run_fetch(db, basic_site())
    failing = basic_site(**{"/company/": httpx.Response(503)})
    result = run_fetch(db, failing, force=True)
    assert result.status == "http_error"
    (row,) = page_rows(db)
    assert row.status == "ok"
    assert "Jane Doe" in row.text


def test_gone_page_replaces_the_good_copy(db: DbCall) -> None:
    run_fetch(db, basic_site())
    run_fetch(db, basic_site(**{"/company/": httpx.Response(410)}), force=True)
    (row,) = page_rows(db)
    assert (row.status, row.http_status, row.text) == ("http_error", 410, None)


def test_5xx_is_retried_before_giving_up(db: DbCall) -> None:
    attempts = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return html_response() if attempts["n"] == 3 else httpx.Response(502)

    result = run_fetch(db, basic_site(**{"/company/": flaky}))
    assert result.status == "ok"
    assert attempts["n"] == 3


def test_network_error_is_a_fetch_error_and_not_cached(db: DbCall) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    site = basic_site(**{"/company/": boom})
    assert run_fetch(db, site).status == "fetch_error"
    assert not run_fetch(db, site).from_cache


def test_non_html_is_skipped_without_storing_the_body(db: DbCall) -> None:
    pdf = httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})
    result = run_fetch(db, basic_site(**{"/company/": pdf}))
    assert result.status == "skipped_non_html"
    (row,) = page_rows(db)
    assert row.text is None


def test_disallowed_path_is_blocked_by_robots(db: DbCall) -> None:
    site = basic_site(**{"/private/x": html_response()})
    result = run_fetch(db, site, "https://www.example.com/private/x")
    assert result.status == "blocked_by_robots"
    assert site.page_requests() == []


def test_missing_robots_txt_allows_everything(db: DbCall) -> None:
    site = Site({"/company/": html_response()})  # /robots.txt -> 404
    assert run_fetch(db, site).status == "ok"


@pytest.mark.parametrize("code", [403, 500])
def test_unreachable_robots_txt_blocks_the_domain(db: DbCall, code: int) -> None:
    site = Site({"/robots.txt": httpx.Response(code), "/company/": html_response()})
    assert run_fetch(db, site).status == "blocked_by_robots"
    assert site.page_requests() == []


def test_redirects_are_followed_and_final_url_stored(db: DbCall) -> None:
    redirect = httpx.Response(301, headers={"location": "/company/"})
    result = run_fetch(db, basic_site(**{"/old/": redirect}), "https://www.example.com/old/")
    assert result.status == "ok"
    assert result.final_url == URL
    (row,) = page_rows(db)
    assert row.url == "https://www.example.com/old/"
    assert row.final_url == URL


def test_redirect_loop_is_a_fetch_error(db: DbCall) -> None:
    loop = httpx.Response(302, headers={"location": "/loop/"})
    result = run_fetch(db, basic_site(**{"/loop/": loop}), "https://www.example.com/loop/")
    assert result.status == "fetch_error"


def test_redirect_target_is_checked_against_robots(db: DbCall) -> None:
    redirect = httpx.Response(302, headers={"location": "/private/secret"})
    site = basic_site(**{"/go/": redirect, "/private/secret": html_response()})
    assert run_fetch(db, site, "https://www.example.com/go/").status == "blocked_by_robots"


def test_at_most_one_request_per_second_per_domain(db: DbCall) -> None:
    clock = Clock()
    run_fetch(db, basic_site(), clock=clock)  # robots.txt + page = 2 requests
    assert sum(clock.sleeps) >= 1.0


def test_published_date_is_stored(db: DbCall) -> None:
    result = run_fetch(db, basic_site())
    assert (result.published_date.isoformat(), result.date_kind) == ("2025-03-14", "published")
    (row,) = page_rows(db)
    assert row.date_kind == "published"
