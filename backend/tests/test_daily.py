"""The `daily` command: step order, isolation of failures, company selection, exit code."""

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import cli
from app.agents import daily
from app.agents.daily import DailyContext, StepResult
from app.db.models import Company
from app.loop import run
from tests.conftest import DbCall
from tests.kb_helpers import import_kemira


def fake_step(name: str, status: str = "ok", boom: bool = False, calls: list[str] | None = None):
    async def step(ctx: DailyContext) -> StepResult:
        if calls is not None:
            calls.append(name)
        if boom:
            raise RuntimeError(f"{name} exploded")
        return StepResult(name, status, f"{name} done")

    step.__name__ = f"step_{name}"
    return step


@pytest.fixture
def test_session(test_db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the daily command at the test database."""
    engine = create_async_engine(test_db_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(daily, "get_sessionmaker", lambda: sessions)
    monkeypatch.setattr(daily, "get_engine", lambda: SimpleNamespace(dispose=engine.dispose))


def test_the_default_order_is_ax_competitor_faq_alerts_report() -> None:
    names = [step.__name__.removeprefix("step_") for step in daily.DEFAULT_STEPS]
    assert names == ["ax", "competitor", "faq", "alerts", "report"]


async def test_the_stubs_are_skipped_not_failed() -> None:
    ctx = DailyContext("kemira", "dev", "manual")
    assert (await daily.step_competitor(ctx)).status == "skipped"
    assert (await daily.step_faq(ctx)).status == "skipped"


async def test_one_failing_step_does_not_stop_the_others() -> None:
    calls: list[str] = []
    steps = (
        fake_step("ax", calls=calls),
        fake_step("competitor", boom=True, calls=calls),
        fake_step("faq", "skipped", calls=calls),
        fake_step("alerts", boom=True, calls=calls),
        fake_step("report", calls=calls),
    )
    results = await daily.run_company(DailyContext("kemira", "live", "manual"), steps)

    assert calls == ["ax", "competitor", "faq", "alerts", "report"]
    assert [(r.name, r.status) for r in results] == [
        ("ax", "ok"),
        ("competitor", "failed"),
        ("faq", "skipped"),
        ("alerts", "failed"),
        ("report", "ok"),
    ]
    assert "RuntimeError: competitor exploded" in results[1].message


def test_exit_code_is_1_only_when_a_step_failed(
    db: DbCall, test_session: None, capsys: pytest.CaptureFixture[str]
) -> None:
    db(import_kemira)
    ok = (fake_step("ax", "partial"), fake_step("faq", "skipped"))
    bad = (fake_step("ax"), fake_step("report", boom=True))

    assert run(daily.daily_command("kemira", "manual", "dev", steps=ok)) == 0
    assert run(daily.daily_command("kemira", "manual", "dev", steps=bad)) == 1
    out = capsys.readouterr().out
    assert "== kemira (dev) ==" in out and "partial" in out and "report" in out


def test_without_company_every_monitored_company_runs(db: DbCall, test_session: None) -> None:
    db(import_kemira)
    assert run(daily.companies_to_run(None, "schedule")) == [("kemira", "")]

    async def off(s: AsyncSession) -> None:
        await s.execute(update(Company).values(monitoring_enabled=False))
        await s.commit()

    db(off)
    assert run(daily.companies_to_run(None, "schedule")) == []


def test_a_scheduled_run_respects_the_monitoring_switch(db: DbCall, test_session: None) -> None:
    db(import_kemira)

    async def off(s: AsyncSession) -> None:
        await s.execute(update(Company).values(monitoring_enabled=False))
        await s.commit()

    db(off)
    assert run(daily.companies_to_run("kemira", "schedule")) == [
        ("kemira", "monitoring is switched off")
    ]
    assert run(daily.companies_to_run("kemira", "manual")) == [("kemira", "")]


def test_unknown_company_is_an_error(db: DbCall, test_session: None) -> None:
    with pytest.raises(SystemExit, match="unknown company 'nope'"):
        run(daily.companies_to_run("nope", "manual"))


def test_a_company_without_monitoring_is_not_started(
    db: DbCall, test_session: None, capsys: pytest.CaptureFixture[str]
) -> None:
    db(import_kemira)

    async def off(s: AsyncSession) -> None:
        await s.execute(update(Company).values(monitoring_enabled=False))
        await s.commit()

    db(off)
    calls: list[str] = []
    code = run(
        daily.daily_command("kemira", "schedule", "live", steps=(fake_step("ax", calls=calls),))
    )
    assert code == 0 and calls == []
    assert "skipped: monitoring is switched off" in capsys.readouterr().out


def test_cli_passes_the_options(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[Any, ...]] = []

    async def fake(company: str | None, trigger: str, mode: str, force: bool) -> int:
        seen.append((company, trigger, mode, force))
        return 0

    monkeypatch.setattr(cli, "daily_command", fake)
    assert cli.main(["daily"]) == 0
    assert (
        cli.main(
            ["daily", "--company", "kemira", "--trigger", "schedule", "--mode", "dev", "--force"]
        )
        == 0
    )
    assert seen == [(None, "manual", "live", False), ("kemira", "schedule", "dev", True)]


def test_cli_email_commands_pass_the_options(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[Any, ...]] = []

    async def fake(kind: str, company: str, mode: str, force: bool) -> int:
        seen.append((kind, company, mode, force))
        return 0

    monkeypatch.setattr(cli, "run_email_command", fake)
    cli.main(["send-report", "--company", "kemira", "--mode", "dev", "--force"])
    cli.main(["send-alerts", "--company", "kemira"])
    cli.main(["send-test-email", "--company", "kemira"])
    assert seen == [
        ("report", "kemira", "dev", True),
        ("alerts", "kemira", "live", False),
        ("test", "kemira", "live", False),
    ]
