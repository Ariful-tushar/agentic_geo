"""Fakes for the knowledge-base tests: bag-of-words embeddings and an in-memory fetcher."""

import hashlib
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.fetch.fetcher import FetchResult
from app.profiles.loader import import_profile, load_profile_file

KEMIRA = Path(__file__).parents[2] / "seed" / "kemira.profile.yaml"
COMPANY_URL = "https://www.kemira.com/company/"
DIM = 768


class FakeEmbeddings(Embeddings):
    """Words are hashed into 768 buckets, so texts that share words are close together."""

    def __init__(self) -> None:
        self.calls = 0
        self.fail_after: int | None = None  # raise after this many document calls

    @staticmethod
    def vector(value: str) -> list[float]:
        vec = [0.0] * DIM
        for word in re.findall(r"[a-z0-9,]+", value.lower()):
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM
            vec[bucket] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.vector(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            from app.llm.limits import DailyStop

            raise DailyStop("gemini", 7200)
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)


def make_page(url: str, body: str, title: str | None = None, **extra: Any) -> FetchResult:
    return FetchResult(
        url=url,
        status="ok",
        final_url=url,
        http_status=200,
        title=title or f"Title of {url.rstrip('/').rsplit('/', 1)[-1]}",
        text=body,
        published_date=extra.pop("published_date", date(2025, 5, 1)),
        date_kind="published",
        **extra,
    )


def failure(url: str, status: str, http_status: int | None) -> FetchResult:
    return FetchResult(url=url, status=status, final_url=url, http_status=http_status)


class FakeFetcher:
    """Serves pages from a dict; anything not listed is a 404."""

    def __init__(self, pages: dict[str, FetchResult]) -> None:
        self.pages = pages

    async def fetch(self, session: AsyncSession, url: str, *, force: bool = False) -> FetchResult:
        return self.pages.get(url) or failure(url, "http_error", 404)

    async def aclose(self) -> None:
        return None


def kemira_pages() -> dict[str, FetchResult]:
    """One short page per knowledge source of the Kemira profile."""
    profile = load_profile_file(KEMIRA)
    pages = {}
    for source in profile.knowledge_sources:
        url = str(source)
        pages[url] = make_page(url, f"Page about {url}. " + "Filler sentence about water. " * 5)
    pages[COMPANY_URL] = make_page(
        COMPANY_URL,
        "About us\nKemira is a global leader in sustainable chemistry for water-intensive "
        "industries.\nIn 2025 we employed approximately 4,900 people worldwide.",
        title="About us - Kemira",
    )
    return pages


async def import_kemira(session: AsyncSession) -> None:
    await import_profile(session, load_profile_file(KEMIRA))


async def count_chunks(session: AsyncSession, url: str | None = None) -> int:
    query = "SELECT count(*) FROM langchain_pg_embedding"
    params: dict[str, str] = {}
    if url:
        query += " WHERE cmetadata->>'url' = :url"
        params["url"] = url
    return (await session.execute(text(query), params)).scalar_one()
