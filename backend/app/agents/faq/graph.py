"""The FAQ agent as a LangGraph graph (SPEC 8.4).

fetch_pages -> extract_questions -> dedupe -> relevance -> draft_answers. Running it again adds
nothing that already exists: stored questions are skipped and only missing drafts are written.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.documents import Document
from langgraph.graph import END, START, StateGraph

from app.agents.faq import nodes
from app.agents.faq.nodes import DraftResult, FaqDeps, FaqState, Verdict
from app.db.session import get_engine, get_sessionmaker
from app.fetch.fetcher import PoliteFetcher
from app.kb.retriever import retrieve
from app.llm.embeddings import GeminiEmbeddings, embed_texts
from app.llm.internal import structured

NodeFn = Callable[[FaqState, FaqDeps], Awaitable[dict[str, Any]]]

NODES: list[tuple[str, NodeFn]] = [
    ("fetch_pages", nodes.fetch_pages),
    ("extract_questions", nodes.extract_questions),
    ("dedupe", nodes.dedupe),
    ("relevance", nodes.relevance),
    ("draft_answers", nodes.draft_answers),
]


def default_deps() -> FaqDeps:
    engine, embeddings = get_engine(), GeminiEmbeddings()

    async def kb_search(company_id: str, query: str) -> list[Document]:
        hits = await retrieve(engine, company_id, query, embeddings=embeddings)
        return [doc for doc, _ in hits]

    async def embed(texts: list[str]) -> list[list[float]]:
        return await embed_texts(texts, "RETRIEVAL_DOCUMENT")

    return FaqDeps(
        sessionmaker=get_sessionmaker(),
        llm=structured,
        fetcher=PoliteFetcher(),
        embed=embed,
        kb_search=kb_search,
    )


def build_graph(deps: FaqDeps):
    def bind(fn: NodeFn):
        async def node(state: FaqState) -> dict[str, Any]:
            return await fn(state, deps)

        return node

    graph = StateGraph(FaqState)
    for name, fn in NODES:
        graph.add_node(name, bind(fn))
    graph.add_edge(START, NODES[0][0])
    names = [name for name, _ in NODES]
    for before, after in zip(names, names[1:], strict=False):
        graph.add_edge(before, after)
    graph.add_edge(names[-1], END)
    return graph.compile()


@dataclass
class FaqResult:
    mode: str = "live"
    found: int = 0  # distinct questions on the source pages
    duplicates: int = 0  # already stored, or near-duplicates
    new: int = 0  # new questions with a verdict (stored in live mode)
    relevant: int = 0
    drafts: int = 0
    unanswerable: int = 0
    postponed: int = 0
    verdicts: list[Verdict] = field(default_factory=list)
    draft_list: list[DraftResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "partial" if self.postponed else "completed"


async def run_faq(deps: FaqDeps, company_id: str, *, mode: str = "live") -> FaqResult:
    state = await build_graph(deps).ainvoke({"company_id": company_id, "mode": mode})
    verdicts = state.get("verdicts", [])
    drafts = state.get("drafts", [])
    return FaqResult(
        mode=mode,
        found=len(state.get("candidates", [])),
        duplicates=state.get("duplicates", 0),
        new=len(verdicts),
        relevant=sum(1 for v in verdicts if v.relevant),
        drafts=len(drafts),
        unanswerable=len(state.get("unanswerable", [])),
        postponed=len(state.get("postponed", [])),
        verdicts=verdicts,
        draft_list=drafts,
        warnings=list(state.get("warnings", [])),
    )
