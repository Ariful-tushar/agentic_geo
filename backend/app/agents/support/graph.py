"""LangGraph workflow and runtime helpers for AI-readiness checks."""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.support import nodes
from app.agents.support.nodes import ReadinessDeps, ReadinessState
from app.db.models import ReadinessCheck
from app.db.session import get_sessionmaker
from app.fetch.fetcher import PoliteFetcher
from app.llm.internal import structured

log = logging.getLogger(__name__)

NodeFn = Callable[[ReadinessState, ReadinessDeps], Awaitable[dict[str, Any]]]
NODES: list[tuple[str, NodeFn]] = [
    ("load_check", nodes.load_check),
    ("fetch_page", nodes.fetch_page),
    ("analyze_page", nodes.analyze_page),
    ("save_result", nodes.save_result),
]


@dataclass(frozen=True)
class ReadinessRunResult:
    id: uuid.UUID
    status: str
    n_questions: int | None
    n_answered: int | None
    n_partial: int | None
    missing: list[dict[str, Any]] | None
    suggestions: list[str] | None
    error: str | None


def default_deps() -> ReadinessDeps:
    return {
        "sessionmaker": get_sessionmaker(),
        "fetcher": PoliteFetcher(),
        "llm": structured,
    }


def build_graph(deps: ReadinessDeps):
    def bind(fn: NodeFn):
        async def node(state: ReadinessState) -> dict[str, Any]:
            return await fn(state, deps)

        return node

    graph = StateGraph(ReadinessState)
    for name, fn in NODES:
        graph.add_node(name, bind(fn))
    graph.add_edge(START, NODES[0][0])
    for (before, _), (after, _) in zip(NODES, NODES[1:], strict=False):
        graph.add_edge(before, after)
    graph.add_edge(NODES[-1][0], END)
    return graph.compile()


async def _run_graph(deps: ReadinessDeps, check_id: uuid.UUID) -> None:
    await build_graph(deps).ainvoke(
        {"check_id": str(check_id), "mode": "live", "results": [], "missing": []}
    )


async def _mark_failed(
    sessionmaker: async_sessionmaker[AsyncSession], check_id: uuid.UUID, error: str
) -> None:
    async with sessionmaker() as session:
        check = await session.get(ReadinessCheck, check_id)
        if check is not None:
            check.status = "failed"
            check.error = error[:500]
            await session.commit()


async def run_readiness(deps: ReadinessDeps, check_id: uuid.UUID) -> ReadinessRunResult:
    """Run one saved check; failures are recorded so polling clients can show the error."""
    try:
        await _run_graph(deps, check_id)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        log.exception("Readiness check %s failed", check_id)
        await _mark_failed(deps["sessionmaker"], check_id, error)
    async with deps["sessionmaker"]() as session:
        check = await session.get(ReadinessCheck, check_id)
        if check is None:
            raise LookupError(f"Readiness check '{check_id}' was not found.")
        return ReadinessRunResult(
            id=check.id,
            status=check.status,
            n_questions=check.n_questions,
            n_answered=check.n_answered,
            n_partial=check.n_partial,
            missing=check.missing,
            suggestions=check.suggestions,
            error=check.error,
        )


async def run_readiness_background(check_id: uuid.UUID) -> None:
    deps = default_deps()
    try:
        await run_readiness(deps, check_id)
    finally:
        await deps["fetcher"].aclose()