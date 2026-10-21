"""The Ax LangGraph graph (SPEC 8.2): ten steps, each one idempotent.

start, ask_engines, ask_rag, judge, daily_accuracy, find_why, mentions, competitor_events,
alerts, finish.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.agents.ax import alerts, mentions, nodes, why
from app.agents.ax.nodes import AxDeps, AxState
from app.config import get_settings
from app.db.models import Run
from app.db.session import get_engine, get_sessionmaker
from app.fetch.fetcher import PoliteFetcher
from app.fetch.wikipedia import get_extract
from app.kb.retriever import retrieve
from app.llm.embeddings import GeminiEmbeddings
from app.llm.engines import enabled_engines
from app.llm.internal import structured

NodeFn = Callable[[AxState, AxDeps], Awaitable[dict[str, Any]]]

NODES: list[tuple[str, NodeFn]] = [
    ("start", nodes.start),
    ("ask_engines", nodes.ask_engines),
    ("ask_rag", nodes.ask_rag),
    ("judge", nodes.judge),
    ("daily_accuracy", nodes.daily_accuracy),
    ("find_why", why.find_why),
    ("mentions", mentions.mentions),
    ("competitor_events", mentions.competitor_events),
    ("alerts", alerts.alerts),
    ("finish", nodes.finish),
]


def local_today() -> date:
    """Today's date in the configured timezone (Europe/Helsinki)."""
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


def default_deps() -> AxDeps:
    """Real engines, real internal AI, real embeddings, the polite fetcher and Wikipedia."""
    engine, embeddings = get_engine(), GeminiEmbeddings()

    async def kb_search(company_id: str, query: str) -> list[Document]:
        hits = await retrieve(engine, company_id, query, embeddings=embeddings)
        return [doc for doc, _ in hits]

    return AxDeps(
        sessionmaker=get_sessionmaker(),
        engine=engine,
        engines=enabled_engines(),
        llm=structured,
        embeddings=embeddings,
        today=local_today,
        fetcher=PoliteFetcher(),
        wikipedia=get_extract,
        kb_search=kb_search,
    )


def build_graph(deps: AxDeps):
    def bind(fn: NodeFn):
        async def node(state: AxState) -> dict[str, Any]:
            return await fn(state, deps)

        return node

    graph = StateGraph(AxState)
    for name, fn in NODES:
        graph.add_node(name, bind(fn))
    graph.add_edge(START, "start")
    graph.add_conditional_edges(
        "start", lambda s: END if s.get("stop") else "ask_engines", ["ask_engines", END]
    )
    chain = [name for name, _ in NODES[1:]]
    for before, after in zip(chain, chain[1:], strict=False):
        graph.add_edge(before, after)
    graph.add_edge(chain[-1], END)
    return graph.compile()


@dataclass
class AxResult:
    status: str
    message: str = ""
    run_id: str = ""
    accuracy: dict[str, float] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


async def run_ax(
    deps: AxDeps, company_id: str, *, mode: str = "live", trigger: str = "manual"
) -> AxResult:
    """Run (or resume) today's Ax run. An unexpected error marks the run `failed`."""
    graph = build_graph(deps)
    try:
        state = await graph.ainvoke(
            {
                "company_id": company_id,
                "mode": mode,
                "trigger": trigger,
                "warnings": [],
                "skipped_engines": [],
                "work": 0,
            }
        )
    except Exception as exc:
        await _mark_failed(deps, company_id, mode, f"{type(exc).__name__}: {exc}"[:500])
        raise
    async with deps.sessionmaker() as session:
        run = await session.get(Run, uuid.UUID(state["run_id"]))
        assert run is not None
        details = run.details or {}
        return AxResult(
            status=state.get("status", run.status),
            message=state.get("message", ""),
            run_id=state["run_id"],
            accuracy=details.get("accuracy", {}),
            details=details,
        )


async def _mark_failed(deps: AxDeps, company_id: str, mode: str, error: str) -> None:
    async with deps.sessionmaker() as session:
        run = await session.scalar(
            select(Run).where(
                Run.company_id == company_id,
                Run.kind == "ax",
                Run.run_date == deps.today(),
                Run.mode == mode,
            )
        )
        if run is not None and run.status == "running":
            run.status = "failed"
            run.details = {**(run.details or {}), "error": error}
            await session.commit()
