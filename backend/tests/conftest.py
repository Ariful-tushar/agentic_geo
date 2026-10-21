"""Shared fixtures. DB tests use a throwaway `answerwatch_test` database on the same server."""

import os
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.db.models import Base
from app.llm.limits import reset_limits
from app.loop import run

TEST_DB = "answerwatch_test"

DbCall = Callable[[Callable[[AsyncSession], Awaitable[Any]]], Any]


def _urls() -> tuple[str, str]:
    """(psycopg admin DSN to the `postgres` db, SQLAlchemy URL of the test db)."""
    url = make_url(os.environ.get("TEST_DATABASE_URL") or get_settings().database_url)
    admin = url.set(drivername="postgresql", database="postgres")
    test = url.set(database=TEST_DB)
    return admin.render_as_string(hide_password=False), test.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def test_db_url() -> Iterator[str]:
    admin_dsn, test_url = _urls()
    try:
        admin = psycopg.connect(admin_dsn, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres is not reachable ({exc}); run: docker compose up -d db")
    name = sql.Identifier(TEST_DB)
    with admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(name))
        try:
            yield test_url
        finally:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name))


@pytest.fixture
def db(test_db_url: str) -> Iterator[DbCall]:
    """Fresh empty tables per test. `db(fn)` runs `async fn(session)` and returns its result."""

    async def reset(create: bool) -> None:
        engine = create_async_engine(test_db_url, poolclass=NullPool)
        async with engine.begin() as conn:
            if create:
                await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            else:  # tables made by langchain-postgres (RAG chunks)
                await conn.exec_driver_sql(
                    "DROP TABLE IF EXISTS langchain_pg_embedding, langchain_pg_collection CASCADE"
                )
            await conn.run_sync(Base.metadata.create_all if create else Base.metadata.drop_all)
        await engine.dispose()

    def call(fn: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
        async def go() -> Any:
            engine = create_async_engine(test_db_url, poolclass=NullPool)
            try:
                async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                    return await fn(session)
            finally:
                await engine.dispose()

        return run(go())

    run(reset(create=True))
    yield call
    run(reset(create=False))


@pytest.fixture(autouse=True)
def _fresh_limits() -> Iterator[None]:
    reset_limits()
    yield
    reset_limits()


@pytest.fixture
def no_db_logging(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace llm_calls logging with an in-memory list; returns the list."""
    calls: list[dict[str, Any]] = []

    async def fake_log_call(**kwargs: Any) -> None:
        calls.append(kwargs)

    for module in ("app.llm.engines", "app.llm.internal", "app.llm.embeddings"):
        monkeypatch.setattr(f"{module}.log_call", fake_log_call)
    return calls


@pytest.fixture
def memory_cache(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    """Replace llm_cache with a dict; returns the dict."""
    store: dict[str, dict[str, Any]] = {}

    async def fake_get(key: str) -> dict[str, Any] | None:
        return store.get(key)

    async def fake_set(key: str, provider: str, model: str, payload: dict[str, Any]) -> None:
        if payload:
            store.setdefault(key, payload)

    for module in ("app.llm.internal", "app.llm.embeddings"):
        monkeypatch.setattr(f"{module}.cache_get", fake_get)
        monkeypatch.setattr(f"{module}.cache_set", fake_set)
    return store
