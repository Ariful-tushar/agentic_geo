"""JobRunner: how the API starts a job (SPEC 3). Both runners call only the CLI dispatcher
`python -m app.cli job <name> --company <id> --trigger manual`.

- `local`: starts that command as a detached background process (development). Its output goes
  to `logs/jobs/<job>-<company>-<time>.log`.
- `github`: asks GitHub Actions to run the `agents` workflow (`workflow_dispatch`), which calls
  the same command.
"""

import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Company, Run
from app.jobs.registry import JOBS
from app.schemas.api import JobName, JobStartOut

BACKEND_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = BACKEND_DIR / "logs" / "jobs"
WORKFLOW_FILE = "agents.yml"
GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"
STALE_AFTER = timedelta(hours=3)  # a "running" run older than this is treated as crashed


class JobStartError(Exception):
    """The job could not be started. The message is safe to show (it never contains a token)."""


class JobNotAvailable(Exception):
    """The job exists in the list but its code is not built yet."""


class JobAlreadyRunning(Exception):
    """The same job is already running for this company."""


def job_args(job: str, company_id: str) -> list[str]:
    """The one command line every runner uses (after `python -m app.cli`)."""
    return ["job", job, "--company", company_id, "--trigger", "manual"]


class JobRunner(Protocol):
    name: str

    async def start(self, job: JobName, company_id: str) -> JobStartOut: ...

    def is_running(self, job: str, company_id: str) -> bool:
        """Does this runner know of a running instance (local processes only)?"""
        ...


# ---- local -----------------------------------------------------------------------------------

Spawn = Callable[[list[str], Path], Any]  # (command, log file) -> object with poll()


def spawn_process(command: list[str], log_file: Path) -> subprocess.Popen[bytes]:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    with log_file.open("ab") as log:
        return subprocess.Popen(  # noqa: S603 - fixed command built from validated values
            command,
            cwd=BACKEND_DIR,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            **kwargs,
        )


class LocalJobRunner:
    name = "local"

    def __init__(self, spawn: Spawn = spawn_process) -> None:
        self._spawn = spawn
        self._processes: dict[tuple[str, str], Any] = {}

    def is_running(self, job: str, company_id: str) -> bool:
        process = self._processes.get((job, company_id))
        return process is not None and process.poll() is None

    async def start(self, job: JobName, company_id: str) -> JobStartOut:
        if self.is_running(job, company_id):
            raise JobAlreadyRunning(f"{job} is already running for {company_id}")
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        log_file = LOG_DIR / f"{job}-{company_id}-{stamp}.log"
        command = [sys.executable, "-m", "app.cli", *job_args(job, company_id)]
        try:
            self._processes[(job, company_id)] = self._spawn(command, log_file)
        except OSError as exc:
            raise JobStartError(f"could not start the local process: {exc.strerror}") from exc
        return JobStartOut(
            job=job,
            company_id=company_id,
            runner=self.name,
            status="started",
            detail=f"log: {log_file}",
        )


# ---- GitHub Actions --------------------------------------------------------------------------


class GithubJobRunner:
    """POST /repos/{repo}/actions/workflows/agents.yml/dispatches (GitHub REST docs:
    'Create a workflow dispatch event'). Needs a fine-grained token with Actions: read and write."""

    name = "github"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def is_running(self, job: str, company_id: str) -> bool:
        return False  # GitHub runs are seen through the runs table (see is_running_in_db)

    async def start(self, job: JobName, company_id: str) -> JobStartOut:
        settings = get_settings()
        if not settings.github_dispatch_token:
            raise JobStartError("GITHUB_DISPATCH_TOKEN is not set")
        if settings.github_repo.startswith("your-user/"):
            raise JobStartError("GITHUB_REPO is not set")
        repo = settings.github_repo
        url = f"{GITHUB_API}/repos/{repo}/actions/workflows/{WORKFLOW_FILE}/dispatches"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.github_dispatch_token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        body = {"ref": settings.github_ref, "inputs": {"job": job, "company": company_id}}
        client = self._client or httpx.AsyncClient(timeout=20)
        try:
            response = await client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise JobStartError(f"could not reach GitHub: {type(exc).__name__}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        if response.status_code not in (200, 204):
            raise JobStartError(github_error(response))
        return JobStartOut(
            job=job,
            company_id=company_id,
            runner=self.name,
            status="started",
            detail=f"workflow {WORKFLOW_FILE} on {settings.github_ref}",
        )


def github_error(response: httpx.Response) -> str:
    code = response.status_code
    try:
        message = str(response.json().get("message", ""))[:200]
    except ValueError:
        message = ""
    hints = {
        401: "the token was rejected (check GITHUB_DISPATCH_TOKEN)",
        403: "the token may not run workflows (needs Actions: read and write on the repo)",
        404: f"repository or workflow not found (check GITHUB_REPO and that {WORKFLOW_FILE} "
        "exists on the branch)",
        422: f"{WORKFLOW_FILE} has no workflow_dispatch trigger, or the inputs were refused",
    }
    return f"GitHub answered {code}: {hints.get(code, 'unexpected answer')}. {message}".strip()


# ---- choosing the runner, and "already running" ---------------------------------------------

_runner: JobRunner | None = None


def get_job_runner() -> JobRunner:
    """The runner chosen by JOB_RUNNER (local | github). One instance per process."""
    global _runner
    wanted = get_settings().job_runner
    if _runner is None or _runner.name != wanted:
        _runner = GithubJobRunner() if wanted == "github" else LocalJobRunner()
    return _runner


async def is_running_in_db(session: AsyncSession, job: str, company_id: str) -> bool:
    """Is a run of this job in progress according to the database (any process, any machine)?"""
    fresh = datetime.now(UTC) - STALE_AFTER
    if job in ("ax", "daily"):  # the daily job spends its time in the Ax run
        run = await session.scalar(
            select(Run.id).where(
                Run.company_id == company_id,
                Run.kind == "ax",
                Run.mode == "live",
                Run.status == "running",
                Run.started_at > fresh,
            )
        )
        return run is not None
    if job == "onboard":
        status = await session.scalar(
            select(Company.onboarding_status).where(Company.id == company_id)
        )
        return status == "building"
    return False


async def start_job(
    session: AsyncSession, runner: JobRunner, job: JobName, company_id: str
) -> JobStartOut:
    """Check availability and "already running", then start the job."""
    spec = JOBS[job]
    if not spec.available:
        raise JobNotAvailable(f"Job '{job}' is not available yet")
    if runner.is_running(job, company_id) or await is_running_in_db(session, job, company_id):
        raise JobAlreadyRunning(f"Job '{job}' is already running for {company_id}")
    return await runner.start(job, company_id)
