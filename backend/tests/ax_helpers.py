"""Shared fakes for the Ax run tests: engines, the AI (judge / why / other names), pages,
Wikipedia and RAG. Nothing here calls a real AI or the internet."""

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from langchain_core.documents import Document
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.ax import nodes
from app.agents.ax.graph import AxResult, run_ax
from app.agents.ax.nodes import AxDeps
from app.db.models import Company
from app.fetch.fetcher import FetchResult
from app.kb.retriever import NOT_FOUND
from app.schemas.agents import Citation as CitationIn
from app.schemas.agents import (
    EngineAnswer,
    JudgeBatch,
    JudgeItem,
    OtherBrands,
    OtherBrandsItem,
    RagResult,
    WhyAnswer,
)
from tests.conftest import DbCall
from tests.kb_helpers import FakeEmbeddings, import_kemira

TODAY = date(2026, 10, 21)
DEV_QUESTIONS = 6  # 4 fact + 2 generic
DEV_FACTS = 4


def default_text(question: str) -> str:
    lowered = question.lower()
    if "revenue" in lowered:
        return "In 2025 Kemira's revenue was EUR 2.8 billion."
    if "employ" in lowered:
        return "Kemira employs approximately 4,900 people."
    if "ceo" in lowered or "headquarter" in lowered or "does kemira do" in lowered:
        return "Kemira is a chemistry company headquartered in Helsinki."
    return "Kemira, Ecolab and Solenis are leading suppliers."


class FakeEngine:
    def __init__(self, engine_id: str, respond: Callable[[str], Any] | None = None) -> None:
        self.id = engine_id
        self.respond = respond or default_text
        self.asked: list[str] = []
        self.key = True
        self.citations: list[CitationIn] = []

    def has_key(self) -> bool:
        return self.key

    async def ask(self, question: str) -> EngineAnswer:
        self.asked.append(question)
        result = self.respond(question)
        if isinstance(result, Exception):
            raise result
        return EngineAnswer(
            text=result, model="fake-model", citations=self.citations, raw_json={"raw": True}
        )


class FakeLlm:
    """Our AI. Judge: `correct` with the whole answer as quote, unless told otherwise.
    Other names: `others[code]`. Why: `why` (a WhyAnswer or a function of the prompt)."""

    def __init__(self, verdicts: dict[str, str] | None = None) -> None:
        self.verdicts = verdicts or {}
        self.others: dict[str, list[str]] = {}
        self.why: WhyAnswer | Callable[[str], WhyAnswer] = WhyAnswer(found=False)
        self.batches: list[list[str]] = []
        self.roles: list[str] = []
        self.prompts: list[str] = []
        self.explode = False

    @property
    def calls(self) -> int:
        return len(self.roles)

    async def __call__(self, role: str, prompt: str, schema: type, **kwargs: Any) -> Any:
        self.roles.append(role)
        self.prompts.append(prompt)
        if schema is JudgeBatch:
            if self.explode:
                raise RuntimeError("judge exploded")
            items = json.loads(prompt.split("ITEMS:\n", 1)[1])
            self.batches.append([i["code"] for i in items])
            return JudgeBatch(
                items=[
                    JudgeItem(
                        code=i["code"],
                        verdict=self.verdicts.get(i["code"], "correct"),  # type: ignore[arg-type]
                        quote=i["ai_answer"],
                        reason="fake judge",
                    )
                    for i in items
                ]
            )
        if schema is OtherBrands:
            items = json.loads(prompt.split("ANSWERS:\n", 1)[1])
            return OtherBrands(
                items=[
                    OtherBrandsItem(code=i["code"], names=self.others.get(i["code"], []))
                    for i in items
                ]
            )
        if schema is WhyAnswer:
            return self.why(prompt) if callable(self.why) else self.why
        raise AssertionError(f"unexpected AI call for {schema}")


class FakePages:
    """The polite fetcher: serves `pages[url] = text`, everything else is a 404."""

    def __init__(self, pages: dict[str, str] | None = None) -> None:
        self.pages = pages or {}
        self.failures: dict[str, tuple[str, int | None]] = {}  # url -> (status, http_status)
        self.fetched: list[str] = []

    async def fetch(self, session: Any, url: str, *, force: bool = False) -> FetchResult:
        self.fetched.append(url)
        if url in self.failures:
            status, code = self.failures[url]
            return FetchResult(url, status, http_status=code)
        if url in self.pages:
            return FetchResult(url, "ok", http_status=200, text=self.pages[url])
        return FetchResult(url, "http_error", http_status=404)

    async def aclose(self) -> None:
        return None


class FakeWikipedia:
    def __init__(self, text: str | None = None) -> None:
        self.text = text
        self.error: Exception | None = None
        self.titles: list[str] = []

    async def __call__(self, title: str) -> str | None:
        self.titles.append(title)
        if self.error:
            raise self.error
        return self.text


class FakeKb:
    """RAG chunk search: returns the given (url, text) chunks."""

    def __init__(self, chunks: list[tuple[str, str]] | None = None) -> None:
        self.chunks = chunks or []
        self.error: Exception | None = None
        self.queries: list[str] = []

    async def __call__(self, company_id: str, query: str) -> list[Document]:
        self.queries.append(query)
        if self.error:
            raise self.error
        return [Document(page_content=t, metadata={"url": u}) for u, t in self.chunks]


@pytest.fixture
def fake_rag(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace rag_answer: `state['answer']` is the text, `state['calls']` counts calls."""
    state: dict[str, Any] = {"calls": 0, "answer": "Helsinki, Finland.", "error": None}

    async def fake(engine: Any, company_id: str, question: str, **kwargs: Any) -> RagResult:
        state["calls"] += 1
        if state["error"]:
            raise state["error"]
        if state["answer"] == NOT_FOUND:
            return RagResult(found=False, answer=NOT_FOUND, raw_json={"draft": {"found": True}})
        return RagResult(
            found=True,
            answer=state["answer"],
            source_urls=["https://www.kemira.com/company/"],
            raw_json={"draft": {"found": True}},
        )

    monkeypatch.setattr(nodes, "rag_answer", fake)
    return state


class World:
    """Everything outside the database that the nodes talk to."""

    def __init__(self) -> None:
        self.pages = FakePages()
        self.wikipedia = FakeWikipedia()
        self.kb = FakeKb()


def make_deps(
    session: AsyncSession, engines: list[FakeEngine], llm: FakeLlm, world: World | None = None
) -> AxDeps:
    engine = session.bind
    world = world or World()
    return AxDeps(
        sessionmaker=async_sessionmaker(engine, expire_on_commit=False),  # type: ignore[arg-type]
        engine=engine,  # type: ignore[arg-type]
        engines=engines,  # type: ignore[arg-type]
        llm=llm,
        embeddings=FakeEmbeddings(),
        today=lambda: TODAY,
        fetcher=world.pages,
        wikipedia=world.wikipedia,
        kb_search=world.kb,
    )


def execute(
    db: DbCall,
    engines: list[FakeEngine],
    llm: FakeLlm | None = None,
    *,
    mode: str = "dev",
    trigger: str = "manual",
    setup: bool = True,
    world: World | None = None,
    today: date | None = None,
) -> AxResult:
    llm = llm or FakeLlm()

    async def go(session: AsyncSession) -> AxResult:
        if setup and await session.scalar(select(func.count()).select_from(Company)) == 0:
            await import_kemira(session)
        deps = make_deps(session, engines, llm, world)
        if today is not None:
            deps.today = lambda: today
        return await run_ax(deps, "kemira", mode=mode, trigger=trigger)

    return db(go)


def query(db: DbCall, fn: Callable[[AsyncSession], Any]) -> Any:
    return db(fn)


async def count(session: AsyncSession, model: type) -> int:
    return await session.scalar(select(func.count()).select_from(model))


def two_engines() -> list[FakeEngine]:
    return [FakeEngine("groq_web"), FakeEngine("gemini_memory")]
