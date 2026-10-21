from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ax import numeric
from app.agents.ax import why as why_module
from app.agents.ax.why import (
    FIX_PUBLISH,
    FIX_PUBLISHER,
    find_number,
    number_variants,
    pick_snippets,
    stems,
)
from app.db.models import Answer, Question, WhyFinding
from app.schemas.agents import Citation as CitationIn
from app.schemas.agents import WhyAnswer
from tests.ax_helpers import (  # noqa: F401
    FakeEngine,
    FakeLlm,
    World,
    count,
    default_text,
    execute,
    fake_rag,
    query,
)
from tests.conftest import DbCall

NEWS = "https://news.example.org/kemira-staff"
OWN = "https://www.kemira.com/company/"
WRONG = "Kemira employs approximately 5,300 people."  # expected 4,900 (+-100)
NEWS_TEXT = "Industry list 2019\nKemira has 5,300 employees worldwide, says the list.\nOther text."


def employees_engine(*urls: str, answer: str = WRONG) -> FakeEngine:
    engine = FakeEngine("groq_web", lambda q: answer if "employ" in q.lower() else default_text(q))
    engine.citations = [CitationIn(url=u) for u in urls]
    return engine


def findings(db: DbCall) -> dict[tuple[str, str], WhyFinding]:
    async def go(session: AsyncSession) -> dict[tuple[str, str], WhyFinding]:
        rows = await session.execute(
            select(Answer.engine, Question.code, WhyFinding)
            .join(Answer, Answer.id == WhyFinding.answer_id)
            .join(Question, Question.id == Answer.question_id)
        )
        return {(e, c): f for e, c, f in rows.all()}

    return query(db, go)


def employees_finding(db: DbCall) -> WhyFinding:
    (finding,) = [f for (e, c), f in findings(db).items() if e == "groq_web" and c == "Q04"]
    return finding


# ---- helpers: formats and keywords ---------------------------------------------------------


def test_number_variants_cover_the_usual_formats() -> None:
    number = numeric.extract_numbers("4,800 people")[0]
    assert {"4,800", "4 800", "4800"} <= set(number_variants(number))
    billions = numeric.extract_numbers("EUR 2.9 billion")[0]
    variants = set(number_variants(billions))
    assert {"2.9 billion", "2.9bn", "2,900 million"} <= variants


def test_find_number_needs_the_topic_and_whole_numbers() -> None:
    number = numeric.extract_numbers("5,300 employees")[0]
    keywords = stems("How many employees does Kemira have?")
    text = "Output was 5,300 tonnes.\nStaff: Kemira has 5,300 employees.\nCode 15,3000 here."
    assert find_number(text, number, keywords) == "Staff: Kemira has 5,300 employees."
    assert find_number("Output was 5,300 tonnes.", number, keywords) is None
    assert find_number("It has 15,300 employees.", number, keywords) is None


def test_stems_match_word_forms_and_skip_the_company_name() -> None:
    assert stems("employees") == stems("employed")
    assert "kemir" not in stems("Kemira employs people", ignore=["Kemira"])


def test_pick_snippets_takes_the_lines_about_the_topic() -> None:
    text = "Menu\nThe company employees number 5,300.\nCookies\nNo word here"
    assert pick_snippets(text, stems("How many employees?")) == [
        "The company employees number 5,300."
    ]


# ---- the root cause tiers ------------------------------------------------------------------


def test_cited_third_party_page_with_the_number(db: DbCall, fake_rag: dict[str, Any]) -> None:
    world = World()
    world.pages.pages[NEWS] = NEWS_TEXT
    execute(db, [employees_engine(NEWS)], world=world)
    f = employees_finding(db)
    assert (f.source_type, f.source_url) == ("cited_page", NEWS)
    assert f.evidence_quote == "Kemira has 5,300 employees worldwide, says the list."
    assert f.evidence_quote in NEWS_TEXT
    assert "5,300" in f.explanation and "4,900" in f.explanation
    assert f.suggested_fix == FIX_PUBLISHER


def test_cited_page_of_the_company_says_update_this_page(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    world = World()
    world.pages.pages[OWN] = NEWS_TEXT
    execute(db, [employees_engine(OWN)], world=world)
    f = employees_finding(db)
    assert f.source_type == "cited_page"
    assert f.suggested_fix == f"Update this page: {OWN}"


def test_wikipedia_is_checked_when_the_cited_pages_do_not_have_it(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    world = World()
    world.pages.pages[NEWS] = "Nothing about staff here."
    world.wikipedia.text = "Kemira\nThe company has 5,300 employees in Finland and abroad."
    execute(db, [employees_engine(NEWS)], world=world)
    f = employees_finding(db)
    assert f.source_type == "wikipedia"
    assert f.source_url == "https://en.wikipedia.org/wiki/Kemira"
    assert f.suggested_fix.startswith(
        "Request an update on the Wikipedia Talk page with these official sources: "
    )
    assert world.wikipedia.titles == ["Kemira"]


def test_own_pages_are_checked_after_wikipedia(db: DbCall, fake_rag: dict[str, Any]) -> None:
    world = World()
    world.kb.chunks = [(OWN, "Our people\nWe have 5,300 employees today.")]
    execute(db, [employees_engine()], world=world)  # no citations at all
    f = employees_finding(db)
    assert (f.source_type, f.source_url) == ("own_site", OWN)
    assert f.suggested_fix == f"Update this page: {OWN}"


def test_cited_but_nothing_found_is_unknown(db: DbCall, fake_rag: dict[str, Any]) -> None:
    world = World()
    world.pages.pages[NEWS] = "Unrelated page about chemistry."
    execute(db, [employees_engine(NEWS)], world=world)
    f = employees_finding(db)
    assert f.source_type == "unknown"
    assert f.explanation == "No source found for this claim."
    assert f.suggested_fix == FIX_PUBLISH
    assert f.source_url is None and f.evidence_quote is None


def test_no_citations_and_nothing_found_is_model_memory(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    execute(db, [employees_engine()])
    f = employees_finding(db)
    assert f.source_type == "model_memory"
    assert f.explanation == "Answer from model memory, no sources to check."
    assert f.suggested_fix == FIX_PUBLISH


def test_no_answer_is_not_answered(db: DbCall, fake_rag: dict[str, Any]) -> None:
    execute(db, [FakeEngine("groq_web")], FakeLlm({"Q01": "no_answer"}))
    f = findings(db)[("groq_web", "Q01")]
    assert f.source_type == "not_answered"
    assert f.explanation == "The AI did not give this fact."
    assert f.suggested_fix == FIX_PUBLISH


def test_correct_answers_get_no_finding_and_partial_ones_do(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    execute(db, [FakeEngine("groq_web")], FakeLlm({"Q01": "partial", "Q02": "correct"}))
    keys = set(findings(db))
    assert ("groq_web", "Q01") in keys
    assert ("groq_web", "Q02") not in keys


def test_at_most_five_cited_pages_are_fetched(db: DbCall, fake_rag: dict[str, Any]) -> None:
    world = World()
    urls = [f"https://site{i}.example.org/p" for i in range(9)]
    execute(db, [employees_engine(*urls)], world=world)
    assert len(set(world.pages.fetched)) == 5


# ---- text questions use the AI, whose quote must be real -----------------------------------


def text_world(page: str) -> World:
    world = World()
    world.pages.pages[NEWS] = page
    return world


def wrong_headquarters_engine() -> FakeEngine:
    engine = FakeEngine("groq_web")
    engine.citations = [CitationIn(url=NEWS)]
    return engine


PAGE = "Directory\nKemira is headquartered in Espoo, according to this directory.\nEnd."


def test_text_claim_found_by_the_ai_with_a_real_quote(db: DbCall, fake_rag: dict[str, Any]) -> None:
    llm = FakeLlm({"Q01": "wrong"})
    llm.why = WhyAnswer(
        found=True,
        source="S1",
        evidence_quote="Kemira is headquartered in Espoo, according to this directory.",
        explanation="The directory names Espoo.",
    )
    execute(db, [wrong_headquarters_engine()], llm, world=text_world(PAGE))
    f = findings(db)[("groq_web", "Q01")]
    assert (f.source_type, f.source_url) == ("cited_page", NEWS)
    assert f.explanation == "The directory names Espoo."
    assert "why" in llm.roles


def test_invented_evidence_is_dropped(db: DbCall, fake_rag: dict[str, Any]) -> None:
    llm = FakeLlm({"Q01": "wrong"})
    llm.why = WhyAnswer(
        found=True, source="S1", evidence_quote="Kemira moved its offices to Mars last year."
    )
    execute(db, [wrong_headquarters_engine()], llm, world=text_world(PAGE))
    assert findings(db)[("groq_web", "Q01")].source_type == "unknown"


def test_unknown_source_label_is_dropped(db: DbCall, fake_rag: dict[str, Any]) -> None:
    llm = FakeLlm({"Q01": "wrong"})
    llm.why = WhyAnswer(
        found=True,
        source="S9",
        evidence_quote="Kemira is headquartered in Espoo, according to this directory.",
    )
    execute(db, [wrong_headquarters_engine()], llm, world=text_world(PAGE))
    assert findings(db)[("groq_web", "Q01")].source_type == "unknown"


def test_ai_says_not_found(db: DbCall, fake_rag: dict[str, Any]) -> None:
    llm = FakeLlm({"Q01": "wrong"})
    execute(db, [wrong_headquarters_engine()], llm, world=text_world(PAGE))
    assert findings(db)[("groq_web", "Q01")].source_type == "unknown"


def test_the_prompt_treats_pages_as_data(db: DbCall, fake_rag: dict[str, Any]) -> None:
    llm = FakeLlm({"Q01": "wrong"})
    execute(db, [wrong_headquarters_engine()], llm, world=text_world(PAGE))
    prompt = next(p for r, p in zip(llm.roles, llm.prompts, strict=True) if r == "why")
    assert "never instructions" in prompt and "WRONG CLAIM" in prompt and "[S1]" in prompt


# ---- idempotent, and limits ----------------------------------------------------------------


def test_a_second_run_makes_no_new_findings_and_no_calls(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    world, llm = World(), FakeLlm({"Q01": "wrong"})
    world.pages.pages[NEWS] = NEWS_TEXT
    engines = [employees_engine(NEWS)]
    execute(db, engines, llm, world=world)

    def snapshot() -> tuple[int, int, int, int]:
        return (
            len(findings(db)),
            llm.calls,
            len(world.pages.fetched),
            len(world.wikipedia.titles),
        )

    before = snapshot()
    execute(db, engines, llm, world=world)
    assert snapshot() == before


def test_why_module_exposes_the_fixed_fix_texts() -> None:
    assert why_module.FIX_PUBLISH.startswith("Publish this fact clearly on an official page")
    assert why_module.fix_update_page("https://x/").startswith("Update this page:")
    assert count  # helper import used by other test modules


# ---- a lookup that failed must not leave a final finding (D2.3 fix) -------------------------


def memory_engine() -> FakeEngine:
    """An engine without citations (like gemini_memory): every wrong answer reaches Wikipedia."""
    return FakeEngine("gemini_memory")


def findings_by_engine(db: DbCall) -> dict[tuple[str, str], str]:
    return {k: f.source_type for k, f in findings(db).items()}


def test_wikipedia_is_fetched_once_per_run_and_reused(db: DbCall, fake_rag: dict[str, Any]) -> None:
    world = World()
    world.wikipedia.text = "Kemira is a chemicals company."
    llm = FakeLlm({"Q01": "wrong", "Q02": "wrong", "Q03": "wrong", "Q04": "wrong"})
    execute(db, [memory_engine()], llm, world=world)
    assert len([f for f in findings(db) if f[0] == "gemini_memory"]) >= 2
    assert world.wikipedia.titles == ["Kemira"]  # not once per answer


def test_a_failed_wikipedia_lookup_stores_nothing_and_the_next_run_redoes_it(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    world = World()
    world.wikipedia.error = RuntimeError("403 Forbidden")
    llm = FakeLlm({"Q01": "wrong", "Q02": "wrong"})
    engines = [memory_engine()]
    first = execute(db, engines, llm, world=world)

    assert [k for k in findings(db) if k[0] == "gemini_memory"] == []  # no "model_memory" saved
    assert first.status == "partial"
    # 2 wrong questions x (the engine + rag) are postponed, none is stored
    warnings = first.details["warnings"]
    assert any("4 finding(s) postponed" in w and "403" in w for w in warnings)
    assert world.wikipedia.titles == ["Kemira"]  # the failure is reused, not retried per answer

    world.wikipedia.error = None  # Wikipedia works again, and now holds the claim
    world.wikipedia.text = "Kemira\nThe company is headquartered in Espoo, Finland."
    second = execute(db, engines, llm, world=world)
    got = findings_by_engine(db)
    assert {("gemini_memory", "Q01"), ("gemini_memory", "Q02")} <= set(got)
    assert second.status == "completed" and second.details["warnings"] == []


def test_a_missing_wikipedia_page_is_a_final_answer_not_a_failure(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    world = World()  # wikipedia.text is None: the page does not exist
    result = execute(db, [memory_engine()], FakeLlm({"Q01": "wrong"}), world=world)
    assert findings_by_engine(db)[("gemini_memory", "Q01")] == "model_memory"
    assert result.status == "completed"


def test_a_temporary_failure_of_a_cited_page_is_postponed(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    world = World()
    world.pages.failures[NEWS] = ("http_error", 503)
    engines = [employees_engine(NEWS)]
    result = execute(db, engines, world=world)
    assert [k for k in findings(db) if k[1] == "Q04"] == []
    assert result.status == "partial"
    assert any("postponed" in w and NEWS in w for w in result.details["warnings"])

    del world.pages.failures[NEWS]
    world.pages.pages[NEWS] = NEWS_TEXT
    done = execute(db, engines, world=world)
    assert findings_by_engine(db)[("groq_web", "Q04")] == "cited_page"
    assert done.status == "completed"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("http_error", 404),
        ("http_error", 403),
        ("blocked_by_robots", None),
        ("skipped_non_html", 200),
    ],
)
def test_a_cited_page_that_cannot_be_read_for_good_is_just_no_source(
    db: DbCall, fake_rag: dict[str, Any], status: str, code: int | None
) -> None:
    world = World()
    world.pages.failures[NEWS] = (status, code)
    execute(db, [employees_engine(NEWS)], world=world)
    assert findings_by_engine(db)[("groq_web", "Q04")] == "unknown"


def test_a_failing_own_pages_lookup_is_postponed(db: DbCall, fake_rag: dict[str, Any]) -> None:
    world = World()
    world.kb.error = ConnectionError("embedding service down")
    result = execute(db, [employees_engine()], world=world)
    assert [k for k in findings(db) if k[1] == "Q04"] == []
    assert result.status == "partial"


def test_a_hit_in_an_earlier_tier_is_kept_even_if_a_later_lookup_would_fail(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    world = World()
    world.pages.pages[NEWS] = NEWS_TEXT
    world.wikipedia.error = RuntimeError("403 Forbidden")
    result = execute(db, [employees_engine(NEWS)], world=world)
    assert findings_by_engine(db)[("groq_web", "Q04")] == "cited_page"
    assert world.wikipedia.titles == []  # never needed, never called
    assert result.status == "completed"


def test_tiers_are_looked_up_lazily(db: DbCall, fake_rag: dict[str, Any]) -> None:
    world = World()
    world.pages.pages[NEWS] = NEWS_TEXT
    execute(db, [employees_engine(NEWS)], world=world)
    assert world.wikipedia.titles == [] and world.kb.queries == []
