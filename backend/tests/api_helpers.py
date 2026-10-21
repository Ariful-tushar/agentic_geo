"""Fixtures for the API tests: an HTTP client on the test database, and a small seeded world."""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.testclient import TestClient

from app.api import auth, routes_admin
from app.api.deps import get_email_sender, get_today
from app.db.models import (
    Alert,
    Answer,
    Citation,
    DailyAccuracy,
    Question,
    Run,
    Score,
    WhyFinding,
)
from app.db.session import get_session
from app.jobs.runner import JobAlreadyRunning, JobStartError, get_job_runner
from app.loop import selector_loop_factory
from app.main import app
from app.schemas.api import JobName, JobStartOut
from tests.conftest import DbCall
from tests.email_helpers import FakeSender
from tests.kb_helpers import import_kemira

D1 = date(2026, 10, 20)
D2 = date(2026, 10, 21)
TODAY = D2
PASSWORD = "s3cret"
ADMIN = {"X-Admin-Token": PASSWORD}


class FakeRunner:
    """Records the jobs the API asks for; can pretend to be busy or to fail."""

    name = "fake"

    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.busy = False
        self.error: str | None = None

    def is_running(self, job: str, company_id: str) -> bool:
        return self.busy

    async def start(self, job: JobName, company_id: str) -> JobStartOut:
        if self.busy:
            raise JobAlreadyRunning("busy")
        if self.error:
            raise JobStartError(self.error)
        self.started.append((job, company_id))
        return JobStartOut(
            job=job, company_id=company_id, runner=self.name, status="started", detail="fake"
        )


class Api:
    """A synchronous test client for the app on the test database."""

    def __init__(
        self, client: TestClient, runner: FakeRunner, db: DbCall, sender: FakeSender
    ) -> None:
        self.client, self.runner, self.sender, self._db = client, runner, sender, db

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.get(path, **kwargs)

    def send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.request(method, path, **kwargs)

    def with_session(self, fn: Callable[[AsyncSession], Awaitable[Any]]) -> Any:
        """Run `async fn(session)` directly on the test database (to seed or to check)."""
        return self._db(fn)


@pytest.fixture
def api(test_db_url: str, db: DbCall, monkeypatch: pytest.MonkeyPatch) -> Iterator[Api]:
    """The real app, talking to the (empty) test database.

    TestClient runs the app on a selector event loop, which psycopg needs on Windows."""
    engine = create_async_engine(test_db_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    runner = FakeRunner()
    sender = FakeSender()
    app.dependency_overrides[get_email_sender] = lambda: sender
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_today] = lambda: TODAY
    app.dependency_overrides[get_job_runner] = lambda: runner
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(admin_password=PASSWORD))
    monkeypatch.setattr(routes_admin, "LOGIN_FAIL_DELAY_SECONDS", 0)
    with TestClient(app, backend_options={"loop_factory": selector_loop_factory}) as client:
        yield Api(client, runner, db, sender)
    app.dependency_overrides.clear()


# ---- a small world: Kemira with two live days and one dev run ---------------------------------


async def add_run(
    session: AsyncSession, day: date, mode: str, status: str = "completed", **details: Any
) -> Run:
    run = Run(
        company_id="kemira",
        kind="ax",
        run_date=day,
        mode=mode,
        status=status,
        trigger="manual",
        started_at=datetime(day.year, day.month, day.day, 7, 0, tzinfo=UTC),
        finished_at=datetime(day.year, day.month, day.day, 7, 30, tzinfo=UTC),
        details=details,
    )
    session.add(run)
    await session.flush()
    return run


async def add_answer(
    session: AsyncSession,
    run: Run,
    question: Question,
    engine: str,
    text: str | None,
    verdict: str | None = None,
    error: str | None = None,
) -> Answer:
    answer = Answer(
        run_id=run.id,
        company_id="kemira",
        question_id=question.id,
        engine=engine,
        text=text,
        error=error,
        raw_json={"secret": "raw"},
    )
    session.add(answer)
    await session.flush()
    if verdict:
        score = {"correct": 1, "partial": 0.5, "wrong": 0, "no_answer": 0}[verdict]
        session.add(
            Score(
                answer_id=answer.id,
                verdict=verdict,
                score=score,
                reason=f"reason {verdict}",
                quote=text,
                quote_verified=True,
                method="judge",
            )
        )
    return answer


async def add_accuracy(
    session: AsyncSession, run: Run, engine: str, accuracy: float, n: int = 4
) -> None:
    session.add(
        DailyAccuracy(
            company_id="kemira",
            run_id=run.id,
            run_date=run.run_date,
            engine=engine,
            mode=run.mode,
            accuracy=accuracy,
            n_questions=n,
        )
    )


async def seed_world(session: AsyncSession) -> dict[str, Any]:
    """Kemira (24 questions) plus:
    - live D1: groq_web Q01 correct, Q02 wrong, Q03 correct, Q04 error; rag Q01 correct
    - live D2: groq_web Q01 wrong (citation + why), Q02 correct; rag Q01 correct; a score_drop alert
    - dev D2: groq_web Q01 correct with a different accuracy (0.123): must never show up
    """
    await import_kemira(session)
    from sqlalchemy import select

    qs = {
        q.code: q
        for q in (await session.scalars(select(Question).where(Question.company_id == "kemira")))
    }
    live1 = await add_run(session, D1, "live", answers_ok=5, accuracy={"groq_web": 0.667})
    live2 = await add_run(
        session, D2, "live", answers_ok=3, warnings=["a warning"], mood="not exposed"
    )
    dev2 = await add_run(session, D2, "dev")

    a1 = await add_answer(session, live1, qs["Q01"], "groq_web", "Helsinki, Finland.", "correct")
    await add_answer(session, live1, qs["Q02"], "groq_web", "A chemicals firm.", "wrong")
    await add_answer(session, live1, qs["Q03"], "groq_web", "EUR 2.8 billion.", "correct")
    await add_answer(session, live1, qs["Q04"], "groq_web", None, error="ConnectionError: down")
    await add_answer(session, live1, qs["Q01"], "rag", "Helsinki.", "correct")
    a2 = await add_answer(session, live2, qs["Q01"], "groq_web", "Espoo, Finland.", "wrong")
    await add_answer(session, live2, qs["Q02"], "groq_web", "Water chemistry.", "correct")
    await add_answer(session, live2, qs["Q01"], "rag", "Helsinki.", "correct")
    dev = await add_answer(session, dev2, qs["Q01"], "groq_web", "Dev answer.", "correct")

    await add_accuracy(session, live1, "groq_web", 0.667, 3)
    await add_accuracy(session, live1, "rag", 1.0, 1)
    await add_accuracy(session, live2, "groq_web", 0.5, 2)
    await add_accuracy(session, live2, "rag", 1.0, 1)
    await add_accuracy(session, dev2, "groq_web", 0.123, 1)
    await add_accuracy(session, dev2, "gemini_memory", 0.123, 1)

    session.add(
        Citation(
            answer_id=a2.id,
            url="https://news.example.org/hq",
            title="HQ news",
            domain="news.example.org",
            owner="third_party",
        )
    )
    session.add(
        WhyFinding(
            answer_id=a2.id,
            source_type="cited_page",
            source_url="https://news.example.org/hq",
            evidence_quote="Kemira is based in Espoo.",
            explanation="The page says Espoo.",
            suggested_fix="Ask the publisher to correct it.",
        )
    )
    session.add(
        Alert(
            company_id="kemira",
            run_date=D2,
            kind="score_drop",
            severity="warning",
            engine="groq_web",
            question_id=qs["Q01"].id,
            before_answer_id=a1.id,
            after_answer_id=a2.id,
            summary="groq_web, Q01: the answer got worse (correct -> wrong).",
        )
    )
    await session.commit()
    return {
        "a1": a1.id,
        "a2": a2.id,
        "dev": dev.id,
        "live2": live2.id,
        "dev_run": dev2.id,
        "q": {code: q.id for code, q in qs.items()},
    }


def seeded(api: Api) -> dict[str, Any]:
    return api.with_session(seed_world)


def old(hours: int) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


def new_id() -> uuid.UUID:
    return uuid.uuid4()
