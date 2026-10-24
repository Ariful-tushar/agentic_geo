"""AI-readiness graph and API tests; no real AI or network calls."""

import json
import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.agents.support.graph import run_readiness
from app.db.models import Company, Question, ReadinessCheck
from app.fetch.fetcher import FetchResult
from app.loop import run
from app.schemas.agents import JudgeBatch, JudgeItem, ReadinessAnalysis, ReadinessAnswer
from tests.api_helpers import ADMIN, Api, api, seeded  # noqa: F401
from tests.conftest import DbCall

PAGE_URL = "https://example.org/company/"
NOT_ON_PAGE = "Not on this page."


class FakeFetcher:
    def __init__(self, result: FetchResult) -> None:
        self.result = result
        self.calls: list[tuple[str, bool]] = []

    async def fetch(self, session: Any, url: str, *, force: bool = False) -> FetchResult:
        self.calls.append((url, force))
        return self.result

    async def aclose(self) -> None:
        return None


class FakeReadinessAi:
    unsupported_first = False

    async def __call__(self, role: str, prompt: str, schema: type, **kwargs: Any) -> Any:
        if schema is ReadinessAnalysis:
            payload = prompt.split("QUESTIONS:\n", 1)[1].split("\n\nPAGE TEXT:\n", 1)[0]
            facts = json.loads(payload)
            answers = []
            for index, fact in enumerate(facts):
                answer = fact["expected_answer"] or "The expected numeric fact."
                evidence_quote = "Expected fact 1."
                if index == 1:
                    answer = "A partly complete response."
                    evidence_quote = "A partly complete response."
                elif index == 2:
                    answer = NOT_ON_PAGE
                    evidence_quote = ""
                if index == 0 and self.unsupported_first:
                    evidence_quote = "This sentence does not appear in the page."
                answers.append(
                    ReadinessAnswer(
                        code=fact["code"], answer=answer, evidence_quote=evidence_quote
                    )
                )
            return ReadinessAnalysis(
                answers=answers,
                suggestions=[
                    "Add the missing location fact near the company introduction.",
                    "Clarify the partly described product fact.",
                    "Add a short heading that states the employee figure.",
                ],
            )
        if schema is JudgeBatch:
            payload = prompt.split("ITEMS:\n", 1)[1]
            items = json.loads(payload)
            return JudgeBatch(
                items=[
                    JudgeItem(
                        code=item["code"],
                        verdict="correct" if item["code"] == "F1" else "partial",
                        quote=item["ai_answer"],
                        reason="Matches expected fact" if item["code"] == "F1" else "Incomplete",
                    )
                    for item in items
                ]
            )
        raise AssertionError(f"Unexpected AI schema: {schema.__name__}")


async def seed_readiness(session: AsyncSession) -> uuid.UUID:
    session.add(Company(id="readiness-test", name="Test Company"))
    session.add_all(
        [
            Question(
                company_id="readiness-test",
                code=f"F{index}",
                kind="fact",
                text=f"Question {index}?",
                expected_answer=f"Expected fact {index}.",
            )
            for index in range(1, 4)
        ]
    )
    check = ReadinessCheck(company_id="readiness-test", url=PAGE_URL, status="queued")
    session.add(check)
    await session.commit()
    return check.id


def test_readiness_graph_fetches_freshly_scores_and_saves(db: DbCall, test_db_url: str) -> None:
    check_id = db(seed_readiness)
    engine = create_async_engine(test_db_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    fetcher = FakeFetcher(
        FetchResult(
            PAGE_URL,
            "ok",
            http_status=200,
            text="Expected fact 1. A partly complete response.",
        )
    )
    ai = FakeReadinessAi()

    async def invoke() -> tuple[Any, ReadinessCheck]:
        result = await run_readiness(
            {
                "sessionmaker": sessions,
                "fetcher": fetcher,
                "llm": ai,
            },
            check_id,
        )
        async with sessions() as session:
            saved = await session.get(ReadinessCheck, check_id)
            assert saved is not None
            return result, saved

    result, saved = run(invoke())
    run(engine.dispose())
    assert fetcher.calls == [(PAGE_URL, True)]
    assert (result.status, result.n_questions, result.n_answered, result.n_partial) == (
        "done",
        3,
        1,
        1,
    )
    assert saved.status == "done"
    assert [item["verdict"] for item in saved.results or []] == ["correct", "partial", "no_answer"]
    assert [item["code"] for item in saved.missing or []] == ["F3"]
    assert len(saved.suggestions or []) == 3


def test_readiness_ignores_answers_without_a_quote_from_the_page(
    db: DbCall, test_db_url: str
) -> None:
    check_id = db(seed_readiness)
    engine = create_async_engine(test_db_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    fetcher = FakeFetcher(
        FetchResult(
            PAGE_URL,
            "ok",
            http_status=200,
            text="Expected fact 1. A partly complete response.",
        )
    )
    ai = FakeReadinessAi()
    ai.unsupported_first = True

    async def invoke() -> Any:
        return await run_readiness(
            {"sessionmaker": sessions, "fetcher": fetcher, "llm": ai}, check_id
        )

    result = run(invoke())
    run(engine.dispose())
    assert result.status == "done"
    assert result.n_answered == 0


def test_readiness_graph_records_fetch_failures(db: DbCall, test_db_url: str) -> None:
    check_id = db(seed_readiness)
    engine = create_async_engine(test_db_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    fetcher = FakeFetcher(FetchResult(PAGE_URL, "http_error", http_status=404))

    async def invoke() -> Any:
        return await run_readiness(
            {"sessionmaker": sessions, "fetcher": fetcher, "llm": FakeReadinessAi()}, check_id
        )

    result = run(invoke())
    run(engine.dispose())
    assert result.status == "failed"
    assert "http_error" in (result.error or "")
    assert result.n_questions is None


def test_readiness_api_starts_check_and_exposes_status(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded(api)
    started: list[uuid.UUID] = []

    async def fake_background(check_id: uuid.UUID) -> None:
        started.append(check_id)

    from app.api import routes_admin

    monkeypatch.setattr(routes_admin, "run_readiness_background", fake_background)
    response = api.send(
        "POST",
        "/api/companies/kemira/readiness",
        json={"url": PAGE_URL},
        headers=ADMIN,
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["company_id"] == "kemira"
    check_id = uuid.UUID(body["id"])
    assert started == [check_id]
    assert api.get(f"/api/readiness/{check_id}").json()["id"] == str(check_id)
    assert [item["id"] for item in api.get("/api/companies/kemira/readiness").json()] == [
        str(check_id)
    ]


def test_readiness_api_validates_url_company_and_admin(api: Api) -> None:
    seeded(api)
    response = api.send(
        "POST",
        "/api/companies/kemira/readiness",
        json={"url": "file:///etc/passwd"},
        headers=ADMIN,
    )
    assert response.status_code == 422
    assert (
        api.send("POST", "/api/companies/kemira/readiness", json={"url": PAGE_URL}).status_code
        == 401
    )
    assert (
        api.send(
            "POST",
            "/api/companies/missing/readiness",
            json={"url": PAGE_URL},
            headers=ADMIN,
        ).status_code
        == 404
    )
    unknown = api.get(f"/api/readiness/{uuid.uuid4()}")
    assert unknown.status_code == 404
