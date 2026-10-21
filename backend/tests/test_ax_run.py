from typing import Any

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ax.graph import run_ax
from app.agents.ax.nodes import classify_owner
from app.db.models import (
    Alert,
    Answer,
    Citation,
    Company,
    CompetitorEvent,
    DailyAccuracy,
    Mention,
    Question,
    Run,
    Score,
    WhyFinding,
)
from app.db.repo import live_daily_accuracy
from app.kb.retriever import NOT_FOUND, KnowledgeBaseEmpty
from app.llm.limits import DailyStop
from app.schemas.agents import Citation as CitationIn
from tests.ax_helpers import (  # noqa: F401
    DEV_FACTS,
    DEV_QUESTIONS,
    TODAY,
    FakeEngine,
    FakeLlm,
    World,
    count,
    default_text,
    execute,
    fake_rag,
    make_deps,
    query,
    two_engines,
)
from tests.conftest import DbCall
from tests.kb_helpers import import_kemira

# ---- the happy path ------------------------------------------------------------------------


def test_dev_run_asks_scores_and_stores_accuracy(db: DbCall, fake_rag: dict[str, Any]) -> None:
    engines, llm = two_engines(), FakeLlm()
    result = execute(db, engines, llm)

    assert result.status == "completed"
    assert all(len(e.asked) == DEV_QUESTIONS for e in engines)  # 4 fact + 2 generic
    assert fake_rag["calls"] == DEV_FACTS

    async def facts(session: AsyncSession) -> dict[str, Any]:
        answers = await count(session, Answer)
        scores = await count(session, Score)
        rows = (await session.scalars(select(DailyAccuracy).order_by(DailyAccuracy.engine))).all()
        run = await session.scalar(select(Run))
        return {
            "answers": answers,
            "scores": scores,
            "accuracy": {r.engine: (float(r.accuracy), r.n_questions, r.n_correct) for r in rows},
            "run": (run.kind, run.run_date, run.status, run.trigger),
        }

    data = query(db, facts)
    assert data["answers"] == 2 * DEV_QUESTIONS + DEV_FACTS
    assert data["scores"] == 3 * DEV_FACTS  # only fact questions are judged, rag included
    assert data["accuracy"] == {
        "gemini_memory": (1.0, 4, 4),
        "groq_web": (1.0, 4, 4),
        "rag": (1.0, 4, 4),
    }
    assert data["run"] == ("ax", TODAY, "completed", "manual")
    assert result.accuracy == {"gemini_memory": 1.0, "groq_web": 1.0, "rag": 1.0}


def test_one_judge_call_per_engine_with_only_fact_questions(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    llm = FakeLlm()
    execute(db, two_engines(), llm)
    assert len(llm.batches) == 3  # groq_web, gemini_memory, rag
    assert all(len(batch) == DEV_FACTS for batch in llm.batches)
    assert all(code.startswith("Q") for batch in llm.batches for code in batch)


def test_only_the_question_text_is_sent_to_the_engines(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    engines = two_engines()
    execute(db, engines)

    async def texts(session: AsyncSession) -> set[str]:
        return set((await session.scalars(select(Question.text))).all())

    assert set(engines[0].asked) <= query(db, texts)


def test_live_mode_asks_every_question(db: DbCall, fake_rag: dict[str, Any]) -> None:
    engines = [FakeEngine("groq_web")]
    execute(db, engines, mode="live")
    assert len(engines[0].asked) == 24
    assert fake_rag["calls"] == 18


# ---- idempotent and resumable --------------------------------------------------------------


def test_second_run_the_same_day_adds_nothing(db: DbCall, fake_rag: dict[str, Any]) -> None:
    engines, llm = two_engines(), FakeLlm()
    execute(db, engines, llm)

    async def totals(session: AsyncSession) -> tuple[int, ...]:
        return tuple(
            [await count(session, m) for m in (Answer, Score, Citation, DailyAccuracy, Run)]
        )

    before = query(db, totals)
    asked = [len(e.asked) for e in engines]
    batches, rag_calls = len(llm.batches), fake_rag["calls"]

    second = execute(db, engines, llm)
    assert second.status == "completed"
    assert second.message == "Today's run is already complete"
    assert query(db, totals) == before
    assert [len(e.asked) for e in engines] == asked
    assert (len(llm.batches), fake_rag["calls"]) == (batches, rag_calls)


def test_failed_questions_are_stored_as_errors_and_retried_on_resume(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    flaky_calls = {"n": 0}

    def flaky(question: str) -> Any:
        if "employ" in question.lower():
            flaky_calls["n"] += 1
            if flaky_calls["n"] == 1:
                return ConnectionError("network down")
        return default_text(question)

    engines = [FakeEngine("groq_web", flaky), FakeEngine("gemini_memory")]
    first = execute(db, engines)
    assert first.status == "partial"
    assert first.details["answers_with_error"] == 1
    assert any("1 question(s) failed" in w for w in first.details["warnings"])

    async def state(session: AsyncSession) -> dict[str, Any]:
        bad = (await session.scalars(select(Answer).where(Answer.error.is_not(None)))).all()
        acc = await session.scalar(select(DailyAccuracy).where(DailyAccuracy.engine == "groq_web"))
        return {
            "errors": [(a.engine, a.text, "ConnectionError" in a.error) for a in bad],
            "scores_for_errors": await session.scalar(
                select(func.count())
                .select_from(Score)
                .join(Answer)
                .where(Answer.error.is_not(None))
            ),
            "n_questions": acc.n_questions,
        }

    mid = query(db, state)
    assert mid["errors"] == [("groq_web", None, True)]
    assert mid["scores_for_errors"] == 0
    assert mid["n_questions"] == DEV_FACTS - 1  # the errored answer is left out of accuracy

    second = execute(db, engines)
    assert second.status == "completed"
    assert len(engines[0].asked) == DEV_QUESTIONS + 1  # only the failed question was asked again
    assert len(engines[1].asked) == DEV_QUESTIONS
    after = query(db, state)
    assert after["errors"] == [] and after["n_questions"] == DEV_FACTS


def test_daily_stop_skips_that_engine_but_not_the_others(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    stopped = FakeEngine("groq_web", lambda q: DailyStop("groq", 7200))
    healthy = FakeEngine("gemini_memory")
    result = execute(db, [stopped, healthy])
    assert result.status == "partial"
    assert result.details["skipped_engines"] == ["groq_web"]
    assert any("groq_web: stopped" in w for w in result.details["warnings"])
    assert len(stopped.asked) == 1  # it stopped at the first question
    assert set(result.accuracy) == {"gemini_memory", "rag"}


def test_engine_with_three_errors_in_a_row_is_stopped(db: DbCall, fake_rag: dict[str, Any]) -> None:
    broken = FakeEngine("groq_web", lambda q: RuntimeError("boom"))
    result = execute(db, [broken, FakeEngine("gemini_memory")])
    assert len(broken.asked) == 3
    assert result.status == "partial"
    assert any("3 errors in a row" in w for w in result.details["warnings"])


def test_engine_without_a_key_is_skipped_with_a_warning(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    no_key = FakeEngine("groq_web")
    no_key.key = False
    result = execute(db, [no_key, FakeEngine("gemini_memory")])
    assert no_key.asked == []
    assert result.status == "partial"
    assert "groq_web: skipped, no API key" in result.details["warnings"]


def test_unexpected_error_marks_the_run_failed_and_a_rerun_recovers(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    engines, llm = two_engines(), FakeLlm()
    llm.explode = True
    with pytest.raises(RuntimeError):
        execute(db, engines, llm)
    status = query(db, lambda s: s.scalar(select(Run.status)))
    assert status == "failed"

    llm.explode = False
    asked = [len(e.asked) for e in engines]
    assert execute(db, engines, llm).status == "completed"
    assert [len(e.asked) for e in engines] == asked  # answers from the failed run were kept


# ---- start node ----------------------------------------------------------------------------


def test_monitoring_off_skips_a_scheduled_run_but_not_a_manual_one(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    async def switch_off(session: AsyncSession) -> None:
        await import_kemira(session)
        (await session.get(Company, "kemira")).monitoring_enabled = False
        await session.commit()

    db(switch_off)
    engines = two_engines()
    skipped = execute(db, engines, trigger="schedule", setup=False)
    assert skipped.status == "skipped"
    assert engines[0].asked == []
    manual = execute(db, engines, trigger="manual", setup=False)
    assert manual.status == "completed"
    assert query(db, lambda s: count(s, Run)) == 1  # the same run row was resumed


def test_unknown_company_is_an_error(db: DbCall) -> None:
    async def go(session: AsyncSession) -> None:
        await run_ax(make_deps(session, [], FakeLlm()), "nope")

    with pytest.raises(ValueError, match="unknown company"):
        db(go)


# ---- RAG and scoring rules -----------------------------------------------------------------


def test_rag_not_found_is_no_answer_by_code_without_a_judge_call(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    fake_rag["answer"] = NOT_FOUND
    llm = FakeLlm()
    result = execute(db, [FakeEngine("groq_web")], llm)
    assert result.accuracy["rag"] == 0.0
    assert len(llm.batches) == 1  # only the engine; nothing was sent for rag

    async def rag_scores(session: AsyncSession) -> list[tuple[str, float, str, str]]:
        rows = await session.execute(
            select(Score.verdict, Score.score, Score.method, Answer.text)
            .join(Answer)
            .where(Answer.engine == "rag")
        )
        return [(v, float(s), m, t) for v, s, m, t in rows.all()]

    rows = query(db, rag_scores)
    assert rows == [("no_answer", 0.0, "judge", NOT_FOUND)] * DEV_FACTS


def test_rag_without_a_knowledge_base_is_skipped_with_a_warning(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    fake_rag["error"] = KnowledgeBaseEmpty("run onboard first")
    result = execute(db, [FakeEngine("groq_web")])
    assert result.status == "partial"
    assert "rag" in result.details["skipped_engines"]
    assert "rag" not in result.accuracy


def test_judge_verdicts_become_scores_and_partial_counts_half(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    llm = FakeLlm({"Q01": "wrong", "Q02": "partial"})
    result = execute(db, [FakeEngine("groq_web")], llm)

    async def counts(session: AsyncSession) -> tuple[int, int, int, int]:
        row = await session.scalar(select(DailyAccuracy).where(DailyAccuracy.engine == "groq_web"))
        return row.n_correct, row.n_partial, row.n_wrong, row.n_no_answer

    # Q01 wrong (0), Q02 partial (0.5), Q03 and Q04 are numbers that match (1 + 1) -> 2.5 / 4
    assert result.accuracy["groq_web"] == pytest.approx(0.625)
    assert query(db, counts) == (2, 1, 1, 0)


def test_numeric_override_beats_the_judge_in_a_full_run(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    def respond(question: str) -> str:
        if "employ" in question.lower():
            return "Kemira employs about 5,100 people."  # outside tolerance 100, inside 2x
        return default_text(question)

    execute(db, [FakeEngine("groq_web", respond)])

    async def employees(session: AsyncSession) -> tuple[str, float, str, bool]:
        row = (
            await session.execute(
                select(Score.verdict, Score.score, Score.method, Score.quote_verified)
                .join(Answer)
                .join(Question, Question.id == Answer.question_id)
                .where(Answer.engine == "groq_web", Question.text.ilike("%employees%"))
            )
        ).one()
        return row[0], float(row[1]), row[2], row[3]

    assert query(db, employees) == ("partial", 0.5, "numeric", True)


def test_citations_are_stored_with_their_owner(db: DbCall, fake_rag: dict[str, Any]) -> None:
    engine = FakeEngine("groq_web")
    engine.citations = [
        CitationIn(url="https://www.kemira.com/company/", title="About"),
        CitationIn(url="https://careers.kemira.com/jobs"),
        CitationIn(url="https://www.ecolab.com/solutions"),
        CitationIn(url="https://notkemira.com/x"),
        CitationIn(url="https://en.wikipedia.org/wiki/Kemira"),
        CitationIn(url="https://en.wikipedia.org/wiki/Kemira"),  # duplicate is stored once
    ]
    execute(db, [engine])

    async def owners(session: AsyncSession) -> set[tuple[str, str, bool]]:
        rows = await session.execute(
            select(Citation.url, Citation.owner, Citation.competitor_id.is_not(None))
            .join(Answer)
            .where(Answer.engine == "groq_web")
        )
        return set(rows.all())

    assert query(db, owners) == {
        ("https://www.kemira.com/company/", "company", False),
        ("https://careers.kemira.com/jobs", "company", False),
        ("https://www.ecolab.com/solutions", "competitor", True),
        ("https://notkemira.com/x", "third_party", False),
        ("https://en.wikipedia.org/wiki/Kemira", "third_party", False),
    }
    assert query(db, lambda s: count(s, Citation)) == 5 * DEV_QUESTIONS + DEV_FACTS


def test_classify_owner_matches_domains_and_subdomains_only() -> None:
    competitor = ("c1", ["ecolab.com"])
    known = [competitor]
    assert classify_owner("https://WWW.Kemira.com/x", ["kemira.com"], known)[0] == "company"
    assert classify_owner("https://a.b.kemira.com/", ["kemira.com"], known)[0] == "company"
    assert classify_owner("https://fakekemira.com/", ["kemira.com"], known)[0] == "third_party"
    assert classify_owner("https://ecolab.com/", ["kemira.com"], known) == ("competitor", "c1")


# ---- dev and live runs of the same day are separate ----------------------------------------


def test_live_run_after_a_dev_run_the_same_day_starts_its_own_run(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    engines = [FakeEngine("groq_web")]
    dev = execute(db, engines, mode="dev")
    assert dev.status == "completed"
    assert len(engines[0].asked) == DEV_QUESTIONS

    live = execute(db, engines, mode="live")
    assert live.status == "completed"
    assert live.message == ""  # not "already complete"
    assert len(engines[0].asked) == DEV_QUESTIONS + 24  # the live run asked all 24 questions
    assert fake_rag["calls"] == DEV_FACTS + 18

    async def state(session: AsyncSession) -> dict[str, Any]:
        runs = (await session.execute(select(Run.mode, Run.status, Run.run_date))).all()
        acc = (
            await session.execute(
                select(
                    DailyAccuracy.mode, DailyAccuracy.engine, DailyAccuracy.n_questions
                ).order_by(DailyAccuracy.mode, DailyAccuracy.engine)
            )
        ).all()
        live_rows = (await session.scalars(live_daily_accuracy("kemira"))).all()
        return {
            "runs": sorted(runs),
            "accuracy": [tuple(r) for r in acc],
            "live_only": sorted((r.mode, r.engine, r.n_questions) for r in live_rows),
        }

    data = query(db, state)
    assert data["runs"] == [("dev", "completed", TODAY), ("live", "completed", TODAY)]
    assert data["accuracy"] == [
        ("dev", "groq_web", DEV_FACTS),
        ("dev", "rag", DEV_FACTS),
        ("live", "groq_web", 18),
        ("live", "rag", 18),
    ]
    # what the API, trend, alerts and emails may read: live rows only
    assert data["live_only"] == [("live", "groq_web", 18), ("live", "rag", 18)]


def test_running_the_same_mode_twice_is_still_complete_but_the_other_mode_is_not(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    engines = [FakeEngine("groq_web")]
    execute(db, engines, mode="live")
    assert execute(db, engines, mode="live").message == "Today's run is already complete"
    asked = len(engines[0].asked)
    dev = execute(db, engines, mode="dev")
    assert dev.message == ""
    assert len(engines[0].asked) == asked + DEV_QUESTIONS


def test_a_failing_dev_run_does_not_touch_the_live_run(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    engines = [FakeEngine("groq_web")]
    execute(db, engines, mode="live")
    llm = FakeLlm()
    llm.explode = True
    with pytest.raises(RuntimeError):
        execute(db, engines, llm, mode="dev")
    statuses = query(db, lambda s: s.execute(select(Run.mode, Run.status)))
    assert sorted(statuses.all()) == [("dev", "failed"), ("live", "completed")]


# ---- a repeat of a completed day does nothing ----------------------------------------------


def busy_setup() -> tuple[list[FakeEngine], FakeLlm, World]:
    """A run in which every node has something to do: wrong answers, citations, names."""

    def respond(question: str) -> str:
        if "employ" in question.lower():
            return "Kemira employs approximately 5,300 people."
        if "leading suppliers of water" in question:
            return "Ecolab leads the market, then Kemira and Veolia."
        return default_text(question)

    engine = FakeEngine("groq_web", respond)
    engine.citations = [CitationIn(url="https://news.example.org/staff")]
    llm = FakeLlm({"Q01": "wrong"})
    llm.others = {"G01": ["Veolia"]}
    world = World()
    world.pages.pages["https://news.example.org/staff"] = "Staff\nKemira has 5,300 employees."
    return [engine], llm, world


async def table_sizes(session: AsyncSession) -> dict[str, int]:
    return {
        m.__tablename__: await count(session, m)
        for m in (Answer, Score, Citation, DailyAccuracy, Run, WhyFinding, Mention)
    } | {"events": await count(session, CompetitorEvent), "alerts": await count(session, Alert)}


def test_second_run_on_a_completed_day_makes_zero_calls_of_any_kind(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    engines, llm, world = busy_setup()
    first = execute(db, engines, llm, world=world)
    assert first.status == "completed" and first.message == ""
    assert first.details["why_findings"] and first.details["mentions"]

    def calls() -> tuple[int, ...]:
        return (
            len(engines[0].asked),
            llm.calls,
            fake_rag["calls"],
            len(world.pages.fetched),
            len(world.wikipedia.titles),
            len(world.kb.queries),
        )

    sizes = query(db, table_sizes)
    finished = query(db, lambda s: s.scalar(select(Run.finished_at)))
    before = calls()

    second = execute(db, engines, llm, world=world)

    assert second.status == "completed"
    assert second.message == "Today's run is already complete"
    assert calls() == before  # no engine, AI, RAG, page, Wikipedia or knowledge-base call
    assert query(db, table_sizes) == sizes
    assert query(db, lambda s: s.scalar(select(Run.finished_at))) == finished
    assert query(db, lambda s: s.scalar(select(Run.status))) == "completed"


def test_a_run_finished_before_the_new_steps_existed_gets_them_filled_in(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    engines, llm, world = busy_setup()
    execute(db, engines, llm, world=world)
    asked, judge_batches = len(engines[0].asked), len(llm.batches)

    async def forget_steps_6_to_9(session: AsyncSession) -> None:
        for model in (WhyFinding, Mention, CompetitorEvent, Alert):
            await session.execute(delete(model))
        run = await session.scalar(select(Run))
        run.details = {k: v for k, v in run.details.items() if k != "mentions_done"}
        await session.commit()

    query(db, forget_steps_6_to_9)
    again = execute(db, engines, llm, world=world)

    assert again.message == ""  # new work was done, so it is not "already complete"
    assert again.status == "completed"
    assert again.details["why_findings"] and again.details["mentions"]
    assert len(engines[0].asked) == asked and len(llm.batches) == judge_batches  # nothing re-asked
