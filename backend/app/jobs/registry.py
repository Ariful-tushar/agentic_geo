"""The jobs the system can run, in one place (SPEC 3 and 11).

`python -m app.cli job <name> --company <id> --trigger <t>` runs a job by name. The CLI, the
API's JobRunner (local and GitHub) and the GitHub workflow all call only that command, so the
mapping from job name to code lives here and nowhere else. A job without a handler is not
available yet; the step that builds it fills in its handler.
"""

import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.db.session import get_engine, get_sessionmaker

# handler(company_id, trigger, mode) -> process exit code
Handler = Callable[[str | None, str, str], Awaitable[int]]


async def onboard_command(company_id: str, trigger: str = "manual") -> int:
    from app.fetch.fetcher import PoliteFetcher
    from app.kb.builder import onboard

    fetcher = PoliteFetcher()
    try:
        async with get_sessionmaker()() as session:
            result = await onboard(session, company_id, fetcher=fetcher)
    finally:
        await fetcher.aclose()
        await get_engine().dispose()
    for url, status in result.sources.items():
        print(f"  {status:<8} {url}")
    print(
        f"Onboarding {result.status}: {result.indexed} pages built, {result.unchanged} unchanged, "
        f"{result.removed} removed, {result.chunks_added} chunks added."
    )
    if result.error:
        print(f"Error: {result.error}")
    return 0 if result.status == "ready" else 1


async def run_ax_command(company_id: str, mode: str = "live", trigger: str = "manual") -> int:
    from app.agents.ax.graph import default_deps, run_ax

    deps = default_deps()
    try:
        result = await run_ax(deps, company_id, mode=mode, trigger=trigger)
    finally:
        await deps.fetcher.aclose()
        await get_engine().dispose()
    print(f"Ax run {result.status}." + (f" {result.message}." if result.message else ""))
    for engine, value in sorted(result.accuracy.items()):
        print(f"  accuracy {engine:<18} {value:.0%}")
    details = result.details
    if details:
        print(
            f"  answers {details.get('answers_ok')}/{details.get('answers_expected')} ok, "
            f"{details.get('answers_with_error')} with error, {details.get('unscored')} unscored"
        )
        print(f"  why findings {details.get('why_findings', {})}")
        print(f"  mentions {details.get('mentions')}")
        print(
            f"  competitor events {details.get('competitor_events', {})}, "
            f"alerts {details.get('alerts', {})}"
        )
        for warning in details.get("warnings", []):
            print(f"  warning: {warning}")
    return 0 if result.status in ("completed", "skipped") else 1


async def run_competitor_command(
    company_id: str, mode: str = "live", trigger: str = "manual"
) -> int:
    from app.agents.competitor.graph import default_deps, run_competitor

    deps = default_deps()
    try:
        result = await run_competitor(deps, company_id, mode=mode)
    finally:
        await deps.fetcher.aclose()
        await get_engine().dispose()
    print(
        f"Competitor agent {result.status}: {result.events} new events, {result.analysed} "
        f"analysed ({result.found} with a report, {result.nothing_found} nothing found), "
        f"{result.postponed} postponed."
    )
    for warning in result.warnings:
        print(f"  warning: {warning}")
    return 0 if result.status == "completed" else 1


async def run_faq_command(company_id: str, mode: str = "live", trigger: str = "manual") -> int:
    from app.agents.faq.graph import default_deps, run_faq

    deps = default_deps()
    try:
        result = await run_faq(deps, company_id, mode=mode)
    finally:
        await deps.fetcher.aclose()
        await get_engine().dispose()
    prefix = "DEV (nothing stored): " if mode == "dev" else ""
    print(
        f"{prefix}FAQ agent {result.status}: {result.found} questions on the pages, "
        f"{result.duplicates} already known, {result.new} new ({result.relevant} relevant), "
        f"{result.drafts} drafts, {result.unanswerable} not answerable from our sources, "
        f"{result.postponed} postponed."
    )
    for verdict in result.verdicts:
        mark = "relevant    " if verdict.relevant else "not relevant"
        print(f"  {mark} {verdict.candidate.text}  ({verdict.reason})")
    if mode == "dev":
        for draft in result.draft_list:
            print(f"  draft for: {draft.text}")
            print(f"    {draft.answer}")
            print(f"    sources: {draft.source_urls}")
    for warning in result.warnings:
        print(f"  warning: {warning}")
    return 0 if result.status == "completed" else 1


async def readiness_command(company_id: str, url: str) -> int:
    from app.agents.support.graph import default_deps, run_readiness
    from app.db import repo
    from app.db.models import Company

    deps = default_deps()
    try:
        async with deps["sessionmaker"]() as session:
            company = await session.get(Company, company_id)
            if company is None:
                print(f"Company '{company_id}' was not found.", file=sys.stderr)
                return 1
            check = await repo.create_readiness_check(session, company_id, url)
        result = await run_readiness(deps, check.id)
    finally:
        await deps["fetcher"].aclose()
        await get_engine().dispose()
    print(f"AI-readiness check {result.status}: {result.id}")
    if result.status == "failed":
        print(f"  error: {result.error}", file=sys.stderr)
        return 1
    print(
        f"  {result.n_answered} of {result.n_questions} fact questions fully answered; "
        f"{result.n_partial} partly answered."
    )
    for missing in result.missing or []:
        print(f"  missing: {missing['question']} (expected: {missing['expected_answer']})")
    for index, suggestion in enumerate(result.suggestions or [], start=1):
        print(f"  suggestion {index}: {suggestion}")
    return 0


async def _job_onboard(company_id: str | None, trigger: str, mode: str) -> int:
    assert company_id
    return await onboard_command(company_id, trigger)


async def _job_ax(company_id: str | None, trigger: str, mode: str) -> int:
    assert company_id
    return await run_ax_command(company_id, mode, trigger)


async def _job_daily(company_id: str | None, trigger: str, mode: str) -> int:
    from app.agents.daily import daily_command

    return await daily_command(company_id, trigger, mode)


async def _job_competitor(company_id: str | None, trigger: str, mode: str) -> int:
    assert company_id
    return await run_competitor_command(company_id, mode, trigger)


async def _job_faq(company_id: str | None, trigger: str, mode: str) -> int:
    assert company_id
    return await run_faq_command(company_id, mode, trigger)


@dataclass(frozen=True)
class Job:
    handler: Handler | None  # None = not available yet
    needs_company: bool = True

    @property
    def available(self) -> bool:
        return self.handler is not None


JOBS: dict[str, Job] = {
    "daily": Job(_job_daily, needs_company=False),
    "ax": Job(_job_ax),
    "competitor": Job(_job_competitor),
    "faq": Job(_job_faq),
    "onboard": Job(_job_onboard),
}


def job_is_available(name: str) -> bool:
    return name in JOBS and JOBS[name].available
