from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ax.mentions import (
    DONE_KEY,
    classify,
    find_brands,
    find_others,
    rank_matches,
)
from app.agents.ax.nodes import Brand
from app.db.models import Answer, CompetitorEvent, Mention, Question, Run
from app.db.repo import live_competitor_events
from app.llm.limits import DailyStop
from tests.ax_helpers import (  # noqa: F401
    FakeEngine,
    FakeLlm,
    World,
    default_text,
    execute,
    fake_rag,
    query,
)
from tests.conftest import DbCall

KEMIRA = Brand("Kemira", ["Kemira Oyj", "Kemira Group"], "company")
ECOLAB = Brand("Ecolab", ["Nalco Water"], "competitor")
SNF = Brand("SNF", [], "competitor")
NALCO = Brand("Nalco", [], "competitor")
BRANDS = [KEMIRA, ECOLAB, SNF, NALCO]


def names(text: str, brands: list[Brand] = BRANDS) -> list[str]:
    return [m.name for m in find_brands(text, brands)]


# ---- alias matching ------------------------------------------------------------------------


def test_matching_is_case_insensitive() -> None:
    assert names("kemira and ECOLAB lead") == ["Kemira", "Ecolab"]


def test_a_short_alias_is_not_found_inside_other_words() -> None:
    assert names("The SNFX group and ASNF Corp") == []
    assert names("SNF, Kemira") == ["SNF", "Kemira"]
    assert names("(SNF) and snf-floerger") == ["SNF"]  # punctuation counts as a boundary


def test_aliases_are_found_and_report_the_main_name() -> None:
    assert names("Kemira Oyj is Finnish; Nalco Water belongs to Ecolab") == ["Kemira", "Ecolab"]


def test_longest_alias_wins_over_a_shorter_one_inside_it() -> None:
    # "Nalco Water" is an Ecolab alias; the separate brand "Nalco" must not claim the same words
    assert names("Nalco Water is large") == ["Ecolab"]
    assert names("Nalco is large") == ["Nalco"]
    assert names("Kemira Group and Kemira") == ["Kemira"]


def test_rank_is_the_order_of_first_appearance() -> None:
    text = "Ecolab leads. Kemira follows, then SNF; Kemira again and Ecolab again."
    tracked = find_brands(text, BRANDS)
    assert [(m.name, r) for m, r in rank_matches(tracked, [])] == [
        ("Ecolab", 1),
        ("Kemira", 2),
        ("SNF", 3),
    ]


def test_other_names_must_be_in_the_text_and_not_overlap_tracked_brands() -> None:
    text = "Ecolab and Veolia lead; Kemira Finland, veolia and Kurita follow."
    tracked = find_brands(text, BRANDS)
    others = find_others(
        text, ["Veolia", "VEOLIA", "Kurita", "Not here", "", "Kemira Finland"], tracked
    )
    assert [m.name for m in others] == ["Veolia", "Kurita"]  # no duplicate, nothing invented
    ranked = rank_matches(tracked, others)
    assert [(m.name, r) for m, r in ranked][:3] == [("Ecolab", 1), ("Veolia", 2), ("Kemira", 3)]


def test_other_names_are_capped() -> None:
    text = " ".join(f"Firm{i}" for i in range(40))
    assert len(find_others(text, [f"Firm{i}" for i in range(40)], [])) == 15


@pytest.mark.parametrize(
    ("company_rank", "competitors", "expected"),
    [
        (None, [], "company_missing"),
        (None, [("Ecolab", 1)], "company_missing"),
        (2, [("Ecolab", 1)], "competitor_ahead"),
        (1, [("Ecolab", 2)], None),
        (3, [("SNF", 5), ("Ecolab", 2)], "competitor_ahead"),
        (1, [], None),
    ],
)
def test_event_rules(company_rank: int | None, competitors: list, expected: str | None) -> None:
    assert classify(company_rank, competitors) == expected


# ---- in a full run -------------------------------------------------------------------------

AHEAD = "Ecolab leads the market, then Kemira and Veolia."
MISSING = "Solenis and Nalco Water supply coagulants."


def generic_engine(first: str = AHEAD, second: str = MISSING) -> FakeEngine:
    def respond(question: str) -> str:
        if "leading suppliers of water" in question:
            return first
        if "coagulants" in question:
            return second
        return default_text(question)

    return FakeEngine("groq_web", respond)


def llm_with_others() -> FakeLlm:
    llm = FakeLlm()
    llm.others = {"G01": ["Veolia", "Mars Inc"], "G02": []}
    return llm


def mention_rows(db: DbCall) -> dict[tuple[str, str], list[tuple[str, str, int]]]:
    async def go(session: AsyncSession) -> dict:
        rows = await session.execute(
            select(Answer.engine, Question.code, Mention.name, Mention.brand_type, Mention.rank)
            .join(Answer, Answer.id == Mention.answer_id)
            .join(Question, Question.id == Answer.question_id)
            .order_by(Mention.rank)
        )
        out: dict = {}
        for engine, code, name, kind, rank in rows.all():
            out.setdefault((engine, code), []).append((name, kind, rank))
        return out

    return query(db, go)


def events(db: DbCall) -> dict[str, CompetitorEvent]:
    async def go(session: AsyncSession) -> dict[str, CompetitorEvent]:
        rows = await session.execute(
            select(Question.code, CompetitorEvent).join(
                Question, Question.id == CompetitorEvent.question_id
            )
        )
        return dict(rows.all())

    return query(db, go)


def test_mentions_ranks_and_other_names_are_stored(db: DbCall, fake_rag: dict[str, Any]) -> None:
    execute(db, [generic_engine()], llm_with_others())
    rows = mention_rows(db)
    assert rows[("groq_web", "G01")] == [
        ("Ecolab", "competitor", 1),
        ("Kemira", "company", 2),
        ("Veolia", "other", 3),  # "Mars Inc" is not in the text: dropped
    ]
    assert rows[("groq_web", "G02")] == [("Solenis", "competitor", 1), ("Ecolab", "competitor", 2)]


def test_competitor_events_company_missing_and_ahead(db: DbCall, fake_rag: dict[str, Any]) -> None:
    result = execute(db, [generic_engine()], llm_with_others())
    found = events(db)
    assert found["G01"].kind == "competitor_ahead"
    assert found["G01"].company_rank == 2
    assert found["G01"].competitors == [{"name": "Ecolab", "rank": 1}]
    assert found["G02"].kind == "company_missing"
    assert found["G02"].company_rank is None
    assert found["G02"].competitors == [
        {"name": "Solenis", "rank": 1},
        {"name": "Ecolab", "rank": 2},  # "Nalco Water" is an Ecolab alias
    ]
    assert all(e.status == "new" and e.report is None for e in found.values())
    assert result.details["competitor_events"] == {"competitor_ahead": 1, "company_missing": 1}


def test_no_event_when_the_company_is_named_first(db: DbCall, fake_rag: dict[str, Any]) -> None:
    engine = generic_engine("Kemira is first, before Ecolab.", MISSING)
    execute(db, [engine], llm_with_others())
    assert set(events(db)) == {"G02"}
    assert mention_rows(db)[("groq_web", "G01")][0] == ("Kemira", "company", 1)


def test_company_missing_with_no_competitor_named_is_still_an_event(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    execute(db, [generic_engine("Several firms exist.", "Also several.")], llm_with_others())
    found = events(db)
    assert {k: (v.kind, v.competitors) for k, v in found.items()} == {
        "G01": ("company_missing", []),
        "G02": ("company_missing", []),
    }


def test_a_second_run_adds_nothing_and_makes_no_ai_call(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    llm, engines = llm_with_others(), [generic_engine()]
    execute(db, engines, llm)
    rows, evs, calls = mention_rows(db), set(events(db)), llm.calls
    again = execute(db, engines, llm)
    assert (mention_rows(db), set(events(db)), llm.calls) == (rows, evs, calls)
    assert again.message == "Today's run is already complete"


def test_a_stopped_other_names_call_is_retried_and_nothing_half_done_is_stored(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    class Stopping(FakeLlm):
        async def __call__(self, role: str, prompt: str, schema: type, **kwargs: Any) -> Any:
            if role == "extract" and self.explode_extract:
                raise DailyStop("gemini", 7200)
            return await super().__call__(role, prompt, schema, **kwargs)

    llm = Stopping()
    llm.explode_extract = True  # type: ignore[attr-defined]
    llm.others = {"G01": ["Veolia"]}
    engines = [generic_engine()]
    first = execute(db, engines, llm)
    assert first.status == "partial"
    assert any("mentions: groq_web not done yet" in w for w in first.details["warnings"])
    assert mention_rows(db) == {} and events(db) == {}

    llm.explode_extract = False  # type: ignore[attr-defined]
    second = execute(db, engines, llm)
    assert second.status == "completed"
    assert ("groq_web", "G01") in mention_rows(db) and set(events(db)) == {"G01", "G02"}


def test_done_marker_is_kept_in_the_run_details(db: DbCall, fake_rag: dict[str, Any]) -> None:
    execute(db, [generic_engine()], llm_with_others())
    run = query(db, lambda s: s.scalar(select(Run)))
    assert len(run.details[DONE_KEY]) == 2  # two generic answers in dev mode


def test_dev_events_are_hidden_from_the_live_helper(db: DbCall, fake_rag: dict[str, Any]) -> None:
    engines, llm = [generic_engine()], llm_with_others()
    execute(db, engines, llm, mode="dev")
    assert len(events(db)) == 2  # written for dev answers too

    async def live(session: AsyncSession) -> list[CompetitorEvent]:
        return list((await session.scalars(live_competitor_events("kemira"))).all())

    assert query(db, live) == []
    execute(db, engines, llm, mode="live")

    async def live_kinds(session: AsyncSession) -> set[str]:
        rows = (await session.scalars(live_competitor_events("kemira"))).all()
        return {r.kind for r in rows}

    assert query(db, live_kinds) >= {"competitor_ahead", "company_missing"}
