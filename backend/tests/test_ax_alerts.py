from datetime import date
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ax.alerts import Snapshot, decide
from app.db.models import Alert, Answer, Question, Run
from tests.ax_helpers import (  # noqa: F401
    FakeEngine,
    FakeLlm,
    default_text,
    execute,
    fake_rag,
    query,
)
from tests.conftest import DbCall

DAY1, DAY2, DAY3 = date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)
G01, G02 = "leading suppliers of water", "coagulants"


class Script:
    """An engine whose answers can be changed between days."""

    def __init__(self) -> None:
        self.texts: dict[str, str] = {}
        self.engine = FakeEngine("groq_web", self.respond)

    def respond(self, question: str) -> str:
        for key, text in self.texts.items():
            if key in question:
                return text
        return default_text(question)

    def say(self, **texts: str) -> None:
        self.texts = {{"g1": G01, "g2": G02}.get(key, key): value for key, value in texts.items()}


def alerts_of(db: DbCall) -> list[tuple[str, str, str, str]]:
    """(engine, question code, kind, severity), sorted."""

    async def go(session: AsyncSession) -> list[tuple[str, str, str, str]]:
        rows = await session.execute(
            select(Alert.engine, Question.code, Alert.kind, Alert.severity).join(
                Question, Question.id == Alert.question_id
            )
        )
        return sorted(rows.all())

    return query(db, go)


def run_day(db: DbCall, script: Script, day: date, llm: FakeLlm | None = None, **kw: Any) -> Any:
    return execute(db, [script.engine], llm or FakeLlm(), mode="live", today=day, **kw)


# ---- the rules on two snapshots ------------------------------------------------------------


def snap(
    score: float | None = None, rank: int | None = None, ahead: tuple[int, ...] = ()
) -> Snapshot:
    import uuid

    return Snapshot(
        answer_id=uuid.uuid4(),
        score=score,
        mentions_done=True,
        company_rank=rank,
        competitor_ranks=ahead,
    )


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (snap(1.0), snap(0.5), "score_drop"),
        (snap(1.0), snap(0.0), "score_drop"),
        (snap(0.0), snap(1.0), "score_improved"),
        (snap(0.5), snap(0.5), None),
        (snap(None), snap(1.0), None),
    ],
)
def test_fact_rules(before: Snapshot, after: Snapshot, expected: str | None) -> None:
    assert decide("fact", before, after) == expected


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (snap(rank=1), snap(rank=None), "company_dropped"),
        (snap(rank=1), snap(rank=2, ahead=(1,)), "competitor_overtook"),
        (snap(rank=2, ahead=(1,)), snap(rank=2, ahead=(1,)), None),  # already behind before
        (snap(rank=None), snap(rank=2, ahead=(1,)), None),  # missing before, now present but behind
        (snap(rank=None), snap(rank=None), None),
        (snap(rank=1), snap(rank=1), None),
        (snap(rank=2, ahead=(1,)), snap(rank=1), None),
    ],
)
def test_generic_rules(before: Snapshot, after: Snapshot, expected: str | None) -> None:
    assert decide("generic", before, after) == expected


def test_a_snapshot_without_mentions_done_never_alerts() -> None:
    old = Snapshot(answer_id=snap().answer_id, company_rank=1)  # a run from before D2.3
    assert decide("generic", old, snap(rank=None)) is None


# ---- in full runs --------------------------------------------------------------------------


def test_the_first_live_run_has_no_alerts(db: DbCall, fake_rag: dict[str, Any]) -> None:
    run_day(db, Script(), DAY1)
    assert alerts_of(db) == []


def test_score_drop_and_improvement_between_two_days(db: DbCall, fake_rag: dict[str, Any]) -> None:
    script = Script()
    run_day(db, script, DAY1, FakeLlm({"Q01": "wrong", "Q02": "correct"}))
    run_day(db, script, DAY2, FakeLlm({"Q01": "correct", "Q02": "wrong"}))
    got = alerts_of(db)
    assert ("groq_web", "Q01", "score_improved", "info") in got
    assert ("groq_web", "Q02", "score_drop", "warning") in got
    assert ("rag", "Q02", "score_drop", "warning") in got  # the RAG engine is compared too
    assert {code for _, code, _, _ in got} == {"Q01", "Q02"}


def test_alerts_keep_before_and_after_answers_and_a_readable_summary(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    script = Script()
    run_day(db, script, DAY1)
    run_day(db, script, DAY2, FakeLlm({"Q01": "wrong"}))

    async def rows(session: AsyncSession) -> list[tuple[Alert, date, date]]:
        found = (await session.scalars(select(Alert).where(Alert.engine == "groq_web"))).all()
        out = []
        for alert in found:
            before = await session.get(Answer, alert.before_answer_id)
            after = await session.get(Answer, alert.after_answer_id)
            run_before = await session.get(Run, before.run_id)
            run_after = await session.get(Run, after.run_id)
            out.append((alert, run_before.run_date, run_after.run_date))
        return out

    ((alert, before_day, after_day),) = query(db, rows)
    assert (before_day, after_day) == (DAY1, DAY2)
    assert alert.run_date == DAY2 and not alert.emailed
    assert alert.summary.startswith("groq_web, Q01: the answer got worse (correct -> wrong)")
    assert "Where is Kemira headquartered?" in alert.summary


def test_company_dropped_and_competitor_overtook(db: DbCall, fake_rag: dict[str, Any]) -> None:
    script = Script()
    script.say(g1="Kemira leads, then Ecolab.", g2="Kemira first, then SNF.")
    run_day(db, script, DAY1)
    script.say(g1="Ecolab leads, then Kemira.", g2="Only SNF and Solenis are listed.")
    run_day(db, script, DAY2)
    assert [a for a in alerts_of(db) if a[1].startswith("G")] == [
        ("groq_web", "G01", "competitor_overtook", "warning"),
        ("groq_web", "G02", "company_dropped", "warning"),
    ]


def test_no_alert_when_the_company_was_missing_and_is_now_present_but_behind(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    script = Script()
    script.say(g1="Only Ecolab is listed.", g2="Only SNF is listed.")
    run_day(db, script, DAY1)
    script.say(g1="Ecolab leads, then Kemira.", g2="SNF, then Kemira.")
    run_day(db, script, DAY2)
    assert [a for a in alerts_of(db) if a[1].startswith("G")] == []


def test_still_behind_or_still_missing_is_not_news(db: DbCall, fake_rag: dict[str, Any]) -> None:
    script = Script()
    script.say(g1="Ecolab leads, then Kemira.", g2="Only SNF.")
    run_day(db, script, DAY1)
    run_day(db, script, DAY2)
    assert alerts_of(db) == []


def test_trial_runs_make_no_alerts(db: DbCall, fake_rag: dict[str, Any]) -> None:
    script = Script()
    run_day(db, script, DAY1)  # live
    execute(db, [script.engine], FakeLlm({"Q01": "wrong"}), mode="dev", today=DAY2)
    assert alerts_of(db) == []


def test_only_a_completed_live_run_counts_as_the_previous_one(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    script = Script()
    run_day(db, script, DAY1)  # live, correct

    async def make_partial(session: AsyncSession) -> None:
        await session.execute(update(Run).values(status="partial"))
        await session.commit()

    query(db, make_partial)
    run_day(db, script, DAY2, FakeLlm({"Q01": "wrong"}))
    assert alerts_of(db) == []  # the partial run is not used for comparison


def test_a_dev_day_in_between_is_skipped_when_looking_for_the_previous_run(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    script = Script()
    run_day(db, script, DAY1)
    execute(db, [script.engine], FakeLlm({"Q01": "correct"}), mode="dev", today=DAY2)
    run_day(db, script, DAY3, FakeLlm({"Q01": "wrong"}))
    assert ("groq_web", "Q01", "score_drop", "warning") in alerts_of(db)


def test_repeating_the_day_adds_no_alerts_and_no_ai_calls(
    db: DbCall, fake_rag: dict[str, Any]
) -> None:
    script = Script()
    run_day(db, script, DAY1)
    llm = FakeLlm({"Q01": "wrong"})
    run_day(db, script, DAY2, llm)
    before, calls = alerts_of(db), llm.calls
    again = run_day(db, script, DAY2, llm)
    assert alerts_of(db) == before and llm.calls == calls
    assert again.message == "Today's run is already complete"
