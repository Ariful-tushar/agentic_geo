"""Knowledge-base builder (SPEC 8.1): fetch sources -> chunk -> embed -> PGVector `kb_<id>`.

Idempotent and resumable: a page whose text hash is unchanged is skipped, chunks have fixed ids
(so adding is an upsert), each page is committed on its own, and a stopped run (for example the
Gemini daily limit) is finished by simply running `onboard` again.
"""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import get_settings
from app.db import repo
from app.db.models import KnowledgeSource
from app.fetch.fetcher import PoliteFetcher
from app.llm.embeddings import GeminiEmbeddings
from app.llm.limits import DailyStop

log = logging.getLogger(__name__)

CHUNK_SIZE = 1600
CHUNK_OVERLAP = 240
MIN_PAGE_CHARS = 50


def collection_name(company_id: str) -> str:
    return f"kb_{company_id}"


def make_store(engine: AsyncEngine, company_id: str, embeddings: Embeddings) -> PGVector:
    """PGVector collection for one company. 768-dim size comes from the embeddings settings."""
    return PGVector(
        embeddings=embeddings,
        connection=engine,
        collection_name=collection_name(company_id),
        embedding_length=get_settings().embedding_dim,
        async_mode=True,
        create_extension=True,
    )


def chunk_text(page_text: str) -> list[str]:
    """About 1,600 characters, 240 overlap, cut at paragraph/line boundaries where possible."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return [c.strip() for c in splitter.split_text(page_text) if c.strip()]


def content_hash(title: str | None, page_text: str) -> str:
    return hashlib.sha256(f"{title or ''}\x1f{page_text}".encode()).hexdigest()


def chunk_id(company_id: str, url: str, index: int) -> str:
    return f"{company_id}:{hashlib.sha1(url.encode()).hexdigest()[:16]}:{index}"


async def indexed_pages(engine: AsyncEngine, company_id: str) -> dict[str, str]:
    """{url: content_hash} of everything currently stored in this company's collection."""
    query = text(
        "SELECT e.cmetadata->>'url', max(e.cmetadata->>'content_hash') "
        "FROM langchain_pg_embedding e JOIN langchain_pg_collection c ON c.uuid = e.collection_id "
        "WHERE c.name = :name GROUP BY 1"
    )
    async with engine.connect() as conn:
        rows = await conn.execute(query, {"name": collection_name(company_id)})
        return {url: digest for url, digest in rows.all() if url}


async def delete_page_chunks(
    engine: AsyncEngine, company_id: str, url: str, keep_ids: list[str] | None = None
) -> int:
    """Delete this URL's chunks, except `keep_ids`. Returns how many were removed."""
    query = text(
        "DELETE FROM langchain_pg_embedding e USING langchain_pg_collection c "
        "WHERE c.uuid = e.collection_id AND c.name = :name AND e.cmetadata->>'url' = :url "
        "AND NOT (e.id = ANY(:keep))"
    )
    async with engine.begin() as conn:
        result = await conn.execute(
            query,
            {"name": collection_name(company_id), "url": url, "keep": keep_ids or []},
        )
        return result.rowcount


@dataclass
class OnboardResult:
    status: str = "ready"  # ready | failed
    error: str | None = None
    indexed: int = 0  # pages (re)built this run
    unchanged: int = 0
    removed: int = 0  # pages whose chunks were removed
    chunks_added: int = 0
    sources: dict[str, str] = field(default_factory=dict)  # url -> status


def _source_status(fetch_status: str, http_status: int | None) -> str:
    if fetch_status == "blocked_by_robots":
        return "blocked"
    if fetch_status == "skipped_non_html":
        return "skipped"
    if fetch_status == "http_error" and http_status in (404, 410):
        return "gone"
    return "error"


async def _index_page(
    engine: AsyncEngine,
    store: PGVector,
    embeddings: Embeddings,
    company_id: str,
    result,  # FetchResult
    digest: str,
) -> int:
    chunks = chunk_text(result.text or "")
    title = result.title or ""
    vectors = await embeddings.aembed_documents([f"{title}\n\n{c}" for c in chunks])
    ids = [chunk_id(company_id, result.url, i) for i in range(len(chunks))]
    metadatas = [
        {
            "url": result.url,
            "title": result.title,
            "published_date": result.published_date.isoformat() if result.published_date else None,
            "date_kind": result.date_kind,
            "chunk_index": i,
            "content_hash": digest,
        }
        for i in range(len(chunks))
    ]
    await store.aadd_embeddings(texts=chunks, embeddings=vectors, metadatas=metadatas, ids=ids)
    await delete_page_chunks(engine, company_id, result.url, keep_ids=ids)  # stale chunks
    return len(chunks)


async def onboard(
    session: AsyncSession,
    company_id: str,
    *,
    fetcher: PoliteFetcher,
    embeddings: Embeddings | None = None,
    force_fetch: bool = False,
) -> OnboardResult:
    engine = session.bind
    assert isinstance(engine, AsyncEngine), "session must be bound to an AsyncEngine"
    embeddings = embeddings or GeminiEmbeddings()
    await repo.set_onboarding(session, company_id, "building")
    result = OnboardResult()
    try:
        await _build(session, engine, company_id, fetcher, embeddings, force_fetch, result)
    except DailyStop as exc:
        result.status = "failed"
        result.error = f"{exc.provider} daily limit reached; run onboard again later to continue"
    except Exception as exc:
        log.exception("onboarding failed for %s", company_id)
        result.status = "failed"
        result.error = f"{type(exc).__name__}: {exc}"[:500]
    await repo.set_onboarding(session, company_id, result.status, result.error)
    return result


async def _build(
    session: AsyncSession,
    engine: AsyncEngine,
    company_id: str,
    fetcher: PoliteFetcher,
    embeddings: Embeddings,
    force_fetch: bool,
    result: OnboardResult,
) -> None:
    store = make_store(engine, company_id, embeddings)
    await store.acreate_collection()  # extension, langchain tables and the collection
    rows = (
        await session.scalars(
            select(KnowledgeSource).where(KnowledgeSource.company_id == company_id)
        )
    ).all()
    indexed = await indexed_pages(engine, company_id)

    for row in rows:
        if not row.active:
            continue
        page = await fetcher.fetch(session, row.url, force=force_fetch)
        usable = page.status == "ok" and len(page.text or "") >= MIN_PAGE_CHARS
        if not usable:
            # A page with no usable text counts as skipped; a temporary error keeps old chunks.
            row.status = (
                "skipped" if page.status == "ok" else _source_status(page.status, page.http_status)
            )
            if row.status in ("gone", "skipped") and row.url in indexed:
                await delete_page_chunks(engine, company_id, row.url)
                indexed.pop(row.url)
                result.removed += 1
            await session.commit()
            result.sources[row.url] = row.status
            continue
        digest = content_hash(page.title, page.text or "")
        if indexed.get(row.url) == digest:
            result.unchanged += 1
        else:
            try:
                result.chunks_added += await _index_page(
                    engine, store, embeddings, company_id, page, digest
                )
            except DailyStop:
                await session.commit()
                raise
            result.indexed += 1
            indexed[row.url] = digest
        row.status = "ok"
        row.last_built_at = datetime.now(UTC)
        result.sources[row.url] = "ok"
        await session.commit()

    active = {r.url for r in rows if r.active}
    for url in set(indexed) - active:  # pages that left the list
        await delete_page_chunks(engine, company_id, url)
        result.removed += 1
    if not any(status == "ok" for status in result.sources.values()):
        result.status = "failed"
        result.error = "no knowledge source could be read: " + ", ".join(
            f"{status}" for status in sorted(set(result.sources.values()))
        )
