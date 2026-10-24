"""The `daily` command (SPEC 11): for each company, Ax -> competitor -> FAQ -> alert email ->
daily report. Every step is isolated: an error in one step is recorded and the next step still
runs. The FAQ agent is a stub until D5.1.

Exit code: 1 when any step failed, 0 otherwise (a `partial` Ax run is reported, not a failure).
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select

from app.api.deps import get_today
from app.db.models import Company
from app.db.session import get_engine, get_sessionmaker
from app.emails import alert, report
from app.emails.commands import describe
from app.emails.smtp import EmailResult

log = logging.getLogger(__name__)

EMAIL_STATUS = {"sent": "ok", "preview": "ok", "skipped": "skipped", "failed": "failed"}
AX_STATUS = {"completed": "ok", "partial": "partial", "skipped": "skipped"}


@dataclass(frozen=True)
class DailyContext:
    company_id: str
    mode: str
    trigger: str
    force: bool = False


@dataclass(frozen=True)
class StepResult:
    name: str
    status: str  # ok | partial | skipped | failed
    message: str = ""


Step = Callable[[DailyContext], Awaitable[StepResult]]


def from_email(name: str, result: EmailResult) -> StepResult:
    return StepResult(name, EMAIL_STATUS[result.status], describe(result, name))


async def step_ax(ctx: DailyContext) -> StepResult:
    from app.agents.ax.graph import default_deps, run_ax

    deps = default_deps()
    try:
        result = await run_ax(deps, ctx.company_id, mode=ctx.mode, trigger=ctx.trigger)
    finally:
        await deps.fetcher.aclose()
    status = AX_STATUS.get(result.status, "failed")
    return StepResult("ax", status, f"Ax run {result.status}. {result.message}".strip())


async def step_competitor(ctx: DailyContext) -> StepResult:
    from app.agents.competitor.graph import default_deps, run_competitor

    deps = default_deps()
    try:
        result = await run_competitor(deps, ctx.company_id, mode=ctx.mode)
    finally:
        await deps.fetcher.aclose()
    message = (
        f"{result.analysed} of {result.events} new events analysed, {result.postponed} postponed"
    )
    return StepResult("competitor", "partial" if result.postponed else "ok", message)


async def step_faq(ctx: DailyContext) -> StepResult:
    from app.agents.faq.graph import default_deps, run_faq

    deps = default_deps()
    try:
        result = await run_faq(deps, ctx.company_id, mode=ctx.mode)
    finally:
        await deps.fetcher.aclose()
    message = (
        f"{result.new} new questions ({result.relevant} relevant), {result.drafts} drafts, "
        f"{result.postponed} postponed"
    )
    return StepResult("faq", "partial" if result.postponed else "ok", message)


async def step_alerts(ctx: DailyContext) -> StepResult:
    async with get_sessionmaker()() as session:
        company = await session.get(Company, ctx.company_id)
        assert company is not None
        result = await alert.send_alerts(session, company, mode=ctx.mode, today=get_today())
    return from_email("alert email", result)


async def step_report(ctx: DailyContext) -> StepResult:
    async with get_sessionmaker()() as session:
        company = await session.get(Company, ctx.company_id)
        assert company is not None
        result = await report.send_report(
            session, company, mode=ctx.mode, today=get_today(), force=ctx.force
        )
    return from_email("daily report", result)


DEFAULT_STEPS: tuple[Step, ...] = (step_ax, step_competitor, step_faq, step_alerts, step_report)


async def run_company(
    ctx: DailyContext, steps: tuple[Step, ...] = DEFAULT_STEPS
) -> list[StepResult]:
    """Run every step; an exception becomes a `failed` result and never stops the others."""
    results: list[StepResult] = []
    for step in steps:
        name = step.__name__.removeprefix("step_")
        try:
            results.append(await step(ctx))
        except Exception as exc:
            log.exception("daily step %s failed for %s", name, ctx.company_id)
            results.append(StepResult(name, "failed", f"{type(exc).__name__}: {exc}"[:300]))
    return results


async def companies_to_run(company_id: str | None, trigger: str) -> list[tuple[str, str]]:
    """(company id, skip reason or ""). Without --company: every company with monitoring on.
    With --company: that company; a scheduled run still respects the monitoring switch."""
    async with get_sessionmaker()() as session:
        if company_id is None:
            query = select(Company.id).where(Company.monitoring_enabled.is_(True))
            return [(cid, "") for cid in (await session.scalars(query.order_by(Company.id))).all()]
        company = await session.get(Company, company_id)
        if company is None:
            raise SystemExit(f"Error: unknown company '{company_id}'")
        if trigger == "schedule" and not company.monitoring_enabled:
            return [(company_id, "monitoring is switched off")]
        return [(company_id, "")]


async def daily_command(
    company_id: str | None,
    trigger: str = "manual",
    mode: str = "live",
    force: bool = False,
    steps: tuple[Step, ...] = DEFAULT_STEPS,
) -> int:
    failed = False
    try:
        targets = await companies_to_run(company_id, trigger)
        if not targets:
            print("No company has monitoring switched on.")
        for cid, skip_reason in targets:
            print(f"== {cid} ({mode}) ==")
            if skip_reason:
                print(f"  skipped: {skip_reason}")
                continue
            for result in await run_company(DailyContext(cid, mode, trigger, force), steps):
                print(f"  {result.name:<12} {result.status:<8} {result.message}")
                failed = failed or result.status == "failed"
    finally:
        await get_engine().dispose()
    return 1 if failed else 0
