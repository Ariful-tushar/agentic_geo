"""Seeded demo history (runs.trigger = 'simulated'): in the charts only, ignored elsewhere."""

from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.ax.alerts import previous_run
from app.db.models import DailyAccuracy, Run
from tests.api_helpers import D1, D2, Api, add_accuracy, add_run, api, seeded  # noqa: F401

SIM_DAY = date(2026, 10, 19)


async def add_simulated(session: AsyncSession, day: date = SIM_DAY) -> Run:
    run = await add_run(session, day, "live", simulated=True)
    run.trigger = "simulated"
    run.started_at = datetime(2026, 10, 21, 23, 0, tzinfo=UTC)  # "newest", to prove it is ignored
    for engine, accuracy in (("groq_web", 0.9), ("rag", 0.8)):
        await add_accuracy(session, run, engine, accuracy)
    await session.commit()
    return run


def seeded_with_history(api: Api) -> dict[str, Any]:
    ids = seeded(api)
    api.with_session(add_simulated)
    return ids


def test_the_trend_marks_simulated_days(api: Api) -> None:
    seeded_with_history(api)
    points = api.get("/api/companies/kemira/accuracy/trend?days=7").json()
    flags = {(p["date"], p["engine"]): p["simulated"] for p in points}
    assert flags[(str(SIM_DAY), "groq_web")] is True
    assert flags[(str(SIM_DAY), "rag")] is True
    assert flags[(str(D1), "groq_web")] is False and flags[(str(D2), "groq_web")] is False


def test_today_and_its_change_use_real_days_only(api: Api) -> None:
    seeded_with_history(api)

    async def drop_real_d1(session: AsyncSession) -> None:
        await session.execute(delete(DailyAccuracy).where(DailyAccuracy.run_date == D1))
        await session.commit()

    api.with_session(drop_real_d1)
    items = {i["engine"]: i for i in api.get("/api/companies/kemira/accuracy/today").json()}
    assert items["groq_web"]["date"] == str(D2)
    assert items["groq_web"]["previous_date"] is None and items["groq_web"]["delta"] is None


def test_details_list_simulated_days_without_answers(api: Api) -> None:
    seeded_with_history(api)
    body = api.get("/api/companies/kemira/accuracy/details?engine=groq_web").json()
    assert body["simulated_dates"] == [str(SIM_DAY)]
    assert str(SIM_DAY) not in body["dates"]  # nothing is stored for it
    assert all(str(SIM_DAY) not in row["cells"] for row in body["rows"])


def test_runs_and_the_last_run_ignore_simulated_runs(api: Api) -> None:
    ids = seeded_with_history(api)
    runs = api.get("/api/companies/kemira/runs").json()
    assert [r["run_date"] for r in runs if r["mode"] == "live"] == [str(D2), str(D1)]
    (company,) = api.get("/api/companies").json()
    assert company["last_run"]["id"] == str(ids["live2"])


def test_a_simulated_run_is_never_the_previous_run_for_alerts(api: Api) -> None:
    seeded_with_history(api)

    async def look(session: AsyncSession) -> tuple[Any, Any]:
        state: Any = {"company_id": "kemira", "run_date": D1}  # before D1 only demo history exists
        before_real = await previous_run(session, state)
        state = {"company_id": "kemira", "run_date": D2}
        return before_real, await previous_run(session, state)

    before_real, with_real = api.with_session(look)
    assert before_real is None
    assert with_real is not None and with_real.run_date == D1 and with_real.trigger != "simulated"


def test_accuracy_for_emails_skips_simulated_days(api: Api) -> None:
    seeded_with_history(api)
    from app.db import repo

    async def rows(session: AsyncSession) -> list[date]:
        found = await session.scalars(repo.live_daily_accuracy("kemira"))
        return sorted({r.run_date for r in found})

    assert SIM_DAY not in api.with_session(rows)


def test_the_database_accepts_simulated_but_no_other_trigger(api: Api) -> None:
    seeded(api)

    async def add(session: AsyncSession) -> None:
        run = await add_simulated(session, date(2026, 10, 18))
        assert run.trigger == "simulated"
        bad = await add_run(session, date(2026, 10, 17), "live")
        bad.trigger = "bogus"
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
        assert await session.scalar(select(Run.id).where(Run.trigger == "simulated"))

    api.with_session(add)
