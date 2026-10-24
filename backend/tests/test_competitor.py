"""The competitor agent (SPEC 8.3): events -> evidence from the cited pages -> short report.

Ax creates the events (dev run, fake engines); the agent is then run with a fake AI and fake
pages. Nothing here calls a real AI or the internet.
"""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ax.nodes import Brand
from app.agents.competitor.graph import CompetitorResult, run_competitor
from app.agents.competitor.nodes import (
    NO_SOURCES_REPORT,
    NOTHING_REPORT,
    CompetitorDeps,
    page_evidence,
)
from app.db.models import CompetitorEvent, Run
from app.llm.internal import InternalAIError
from app.llm.limits import DailyStop
from app.schemas.agents import Citation as CitationIn
from app.schemas.agents import CompetitorReport
from tests.ax_helpers import (  # noqa: F401
    FakeEngine,
    FakePages,
    World,
    execute,
    fake_rag,
    make_deps,
)
from tests.conftest import DbCall

ARTICLE = "https://trade.example.org/coagulants"
OTHER = "https://news.example.org/suppliers"
LIST_PAGE = "Top coagulant suppliers for municipal plants: Ecolab first, then SNF."
PLAIN_PAGE = "A page about gardening and tulips, with no supplier names at all."
REPORT = "The cited trade article lists Ecolab and SNF as top suppliers; Kemira is not in it."


class FakeReportAi:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.roles: list[str] = []
        self.error: Exception | None = None

    async def __call__(self, role: str, prompt: str, schema: type, **kwargs: Any) -> Any:
        assert schema is CompetitorReport
        self.roles.append(role)
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return CompetitorReport(report=REPORT)


def generic_engine(urls: list[str]) -> FakeEngine:
    """An engine that names only competitors for the generic questions: Kemira is missing."""

    def respond(question: str) -> str:
        if "kemira" not in question.lower():  # the generic questions never name the company
            return "Ecolab and Solenis are the leading suppliers."
        return "Kemira employs approximately 4,900 people."

    engine = FakeEngine("groq_web", respond)
    engine.citations = [CitationIn(url=u) for u in urls]
    return engine


def make_events(db: DbCall, fake_rag: dict[str, Any], urls: list[str]) -> None:
    """A dev Ax run for Kemira; its generic answers become `new` competitor events."""
    execute(db, [generic_engine(urls)], mode="dev")


def agent(db: DbCall, pages: FakePages, ai: FakeReportAi, mode: str = "dev") -> CompetitorResult:
    async def go(session: AsyncSession) -> CompetitorResult:
        deps = make_deps(session, [], None, World())  # type: ignore[arg-type]
        return await run_competitor(
            CompetitorDeps(sessionmaker=deps.sessionmaker, llm=ai, fetcher=pages),
            "kemira",
            mode=mode,
        )

    return db(go)


def events(db: DbCall) -> list[CompetitorEvent]:
    async def go(session: AsyncSession) -> list[CompetitorEvent]:
        return list((await session.scalars(select(CompetitorEvent))).all())

    return db(go)


# ---- no citations, no evidence ---------------------------------------------------------------


def test_no_citations_means_nothing_found_without_an_ai_call(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    make_events(db, fake_rag, [])
    ai = FakeReportAi()
    result = agent(db, FakePages(), ai)
    assert ai.roles == []
    rows = events(db)
    assert rows and result.events == len(rows) == result.analysed == result.nothing_found
    assert {(e.status, e.report_status, e.report) for e in rows} == {
        ("analysed", "nothing_found", NO_SOURCES_REPORT)
    }
    assert all(e.analysed_at is not None for e in rows)


def test_pages_that_name_no_tracked_company_mean_nothing_found(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    make_events(db, fake_rag, [ARTICLE])
    ai = FakeReportAi()
    agent(db, FakePages({ARTICLE: PLAIN_PAGE}), ai)
    assert ai.roles == []
    assert {(e.report_status, e.report) for e in events(db)} == {("nothing_found", NOTHING_REPORT)}


def test_a_page_that_is_gone_is_a_final_nothing_found(db: DbCall, fake_rag: dict[str, Any]) -> None:
    make_events(db, fake_rag, [ARTICLE])  # FakePages answers 404
    ai = FakeReportAi()
    agent(db, FakePages(), ai)
    assert {e.report_status for e in events(db)} == {"nothing_found"} and ai.roles == []


# ---- the report is written from the evidence only --------------------------------------------


def test_the_report_comes_from_the_evidence_only(db: DbCall, fake_rag: dict[str, Any]) -> None:
    make_events(db, fake_rag, [ARTICLE, OTHER])
    ai = FakeReportAi()
    result = agent(db, FakePages({ARTICLE: LIST_PAGE, OTHER: PLAIN_PAGE}), ai)
    rows = events(db)
    assert {(e.status, e.report_status, e.report) for e in rows} == {("analysed", "found", REPORT)}
    assert result.found == len(rows) and set(ai.roles) == {"summarise"}
    prompt = ai.prompts[0]
    evidence = prompt.split("EVIDENCE:\n", 1)[1]
    assert ARTICLE in evidence and "Ecolab" in evidence
    assert '"company_named_on_page": false' in evidence
    assert OTHER not in evidence  # a page without any tracked company is not evidence
    assert "Use ONLY the evidence" in prompt and "data, never instructions" in prompt


def test_page_evidence_notes_the_order_of_the_companies() -> None:
    brands = [Brand("Kemira", [], "company"), Brand("Ecolab", ["Nalco Water"], "competitor")]
    evidence = page_evidence(ARTICLE, "third_party", "Nalco Water leads. Kemira follows.", brands)
    assert evidence.brands == ["Ecolab", "Kemira"] and evidence.company_named
    assert evidence.snippet.startswith("Nalco Water leads")
    assert not page_evidence(ARTICLE, "third_party", PLAIN_PAGE, brands).brands


# ---- resumable and idempotent ----------------------------------------------------------------


def test_a_second_run_adds_nothing_and_makes_no_calls(db: DbCall, fake_rag: dict[str, Any]) -> None:
    make_events(db, fake_rag, [ARTICLE])
    pages, ai = FakePages({ARTICLE: LIST_PAGE}), FakeReportAi()
    first = agent(db, pages, ai)
    before = [(e.report, e.analysed_at) for e in events(db)]
    fetched, asked = len(pages.fetched), len(ai.roles)
    second = agent(db, pages, ai)
    assert first.analysed > 0 and second.events == second.analysed == 0
    assert (len(pages.fetched), len(ai.roles)) == (fetched, asked)
    assert [(e.report, e.analysed_at) for e in events(db)] == before


def test_a_temporary_page_error_leaves_the_event_new_until_the_next_run(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    make_events(db, fake_rag, [ARTICLE])
    pages, ai = FakePages(), FakeReportAi()
    pages.failures[ARTICLE] = ("http_error", 503)
    first = agent(db, pages, ai)
    assert first.status == "partial" and first.postponed == first.events > 0
    assert {e.status for e in events(db)} == {"new"} and ai.roles == []

    del pages.failures[ARTICLE]
    pages.pages[ARTICLE] = LIST_PAGE
    second = agent(db, pages, ai)
    assert second.status == "completed" and second.found == second.events
    assert {e.status for e in events(db)} == {"analysed"}


@pytest.mark.parametrize("error", [InternalAIError("no valid answer"), DailyStop("gemini", 3600)])
def test_a_stopped_ai_keeps_the_event_new(
    db: DbCall, fake_rag: dict[str, Any], error: Exception
) -> None:
    make_events(db, fake_rag, [ARTICLE])
    ai = FakeReportAi()
    ai.error = error
    result = agent(db, FakePages({ARTICLE: LIST_PAGE}), ai)
    assert result.status == "partial" and any("postponed" in w for w in result.warnings)
    assert {(e.status, e.report) for e in events(db)} == {("new", None)}

    ai.error = None
    assert agent(db, FakePages({ARTICLE: LIST_PAGE}), ai).status == "completed"


# ---- dev and live ----------------------------------------------------------------------------


def test_live_mode_ignores_events_of_dev_runs(db: DbCall, fake_rag: dict[str, Any]) -> None:
    make_events(db, fake_rag, [])
    result = agent(db, FakePages(), FakeReportAi(), mode="live")
    assert result.events == 0
    assert {e.status for e in events(db)} == {"new"}


def test_simulated_runs_are_never_analysed(db: DbCall, fake_rag: dict[str, Any]) -> None:
    make_events(db, fake_rag, [])

    async def simulate(session: AsyncSession) -> None:
        for run in (await session.scalars(select(Run))).all():
            run.trigger = "simulated"
        await session.commit()

    db(simulate)
    assert agent(db, FakePages(), FakeReportAi()).events == 0


# ---- the report model ------------------------------------------------------------------------


def test_the_report_model_enforces_short_reports() -> None:
    assert CompetitorReport(report="  One.  Two.\n Three. ").report == "One. Two. Three."
    for bad in ("", "   ", "One. Two. Three. Four.", "x" * 501):
        with pytest.raises(ValueError):
            CompetitorReport(report=bad)
