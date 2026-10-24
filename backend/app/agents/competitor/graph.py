"""The competitor agent as a LangGraph graph (SPEC 8.3).

load_events -> collect_evidence -> write_reports -> save_reports. Events that cannot be finished
now stay `new`, so running the command again completes them and never repeats finished work.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.competitor import nodes
from app.agents.competitor.nodes import CompetitorDeps, CompetitorState
from app.db.session import get_sessionmaker
from app.fetch.fetcher import PoliteFetcher
from app.llm.internal import structured

NodeFn = Callable[[CompetitorState, CompetitorDeps], Awaitable[dict[str, Any]]]

NODES: list[tuple[str, NodeFn]] = [
    ("load_events", nodes.load_events),
    ("collect_evidence", nodes.collect_evidence),
    ("write_reports", nodes.write_reports),
    ("save_reports", nodes.save_reports),
]


def default_deps() -> CompetitorDeps:
    return CompetitorDeps(sessionmaker=get_sessionmaker(), llm=structured, fetcher=PoliteFetcher())


def build_graph(deps: CompetitorDeps):
    def bind(fn: NodeFn):
        async def node(state: CompetitorState) -> dict[str, Any]:
            return await fn(state, deps)

        return node

    graph = StateGraph(CompetitorState)
    for name, fn in NODES:
        graph.add_node(name, bind(fn))
    graph.add_edge(START, NODES[0][0])
    names = [name for name, _ in NODES]
    for before, after in zip(names, names[1:], strict=False):
        graph.add_edge(before, after)
    graph.add_edge(names[-1], END)
    return graph.compile()


@dataclass
class CompetitorResult:
    events: int = 0  # new events found at the start
    analysed: int = 0
    found: int = 0
    nothing_found: int = 0
    postponed: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "partial" if self.postponed else "completed"


async def run_competitor(
    deps: CompetitorDeps, company_id: str, *, mode: str = "live"
) -> CompetitorResult:
    state = await build_graph(deps).ainvoke({"company_id": company_id, "mode": mode})
    reports = state.get("reports", {})
    saved = state.get("saved", 0)
    return CompetitorResult(
        events=len(state.get("events", [])),
        analysed=saved,
        found=sum(1 for status, _ in reports.values() if status == "found"),
        nothing_found=sum(1 for status, _ in reports.values() if status == "nothing_found"),
        postponed=len(state.get("postponed", [])),
        warnings=list(state.get("warnings", [])),
    )
