import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app import cli
from app.jobs import registry, runner
from app.jobs.registry import JOBS, job_is_available
from app.jobs.runner import (
    GithubJobRunner,
    JobAlreadyRunning,
    JobNotAvailable,
    JobStartError,
    LocalJobRunner,
    dispatch_faq_source_update,
    github_error,
    job_args,
    start_job,
)

TOKEN = "ghp_super_secret_token"


# ---- the one command every runner uses -----------------------------------------------------


def test_job_args_are_the_dispatcher_command() -> None:
    assert job_args("ax", "kemira") == ["job", "ax", "--company", "kemira", "--trigger", "manual"]


def test_the_registry_names_the_five_jobs_and_all_are_available() -> None:
    assert set(JOBS) == {"daily", "ax", "competitor", "faq", "onboard"}
    available = {name for name in JOBS if job_is_available(name)}
    assert available == {"daily", "ax", "competitor", "faq", "onboard"}
    assert not job_is_available("nope")
    assert JOBS["daily"].needs_company is False  # daily can run for every company


def test_the_cli_parser_accepts_exactly_the_registry_names() -> None:
    parser = cli.build_parser()
    for name in JOBS:
        args = parser.parse_args(["job", name, "--company", "kemira", "--trigger", "schedule"])
        assert (args.name, args.company, args.trigger, args.mode) == (
            name,
            "kemira",
            "schedule",
            "live",
        )
    with pytest.raises(SystemExit):
        parser.parse_args(["job", "bogus"])


# ---- the dispatcher ------------------------------------------------------------------------


def patch_handler(monkeypatch: pytest.MonkeyPatch, name: str) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    async def handler(company: str | None, trigger: str, mode: str) -> int:
        calls.append((company, trigger, mode))
        return 0

    monkeypatch.setitem(JOBS, name, registry.Job(handler))
    return calls


def test_dispatcher_runs_the_handler_of_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_handler(monkeypatch, "ax")
    code = cli.main(["job", "ax", "--company", "kemira", "--trigger", "schedule"])
    assert code == 0 and calls == [("kemira", "schedule", "live")]


def test_dispatcher_passes_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = patch_handler(monkeypatch, "ax")
    cli.main(["job", "ax", "--company", "kemira", "--mode", "dev"])
    assert calls == [("kemira", "manual", "dev")]


def test_dispatcher_says_not_available_yet(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(JOBS, "faq", registry.Job(None))
    assert cli.main(["job", "faq", "--company", "kemira"]) == 2
    assert "Job 'faq' is not available yet" in capsys.readouterr().err


def test_dispatcher_needs_a_company_for_company_jobs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = patch_handler(monkeypatch, "ax")
    assert cli.main(["job", "ax"]) == 2
    assert "needs --company" in capsys.readouterr().err and calls == []


def test_run_ax_and_onboard_commands_use_the_same_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[Any, ...]] = []

    async def fake_ax(company: str, mode: str, trigger: str) -> int:
        seen.append(("ax", company, mode, trigger))
        return 0

    async def fake_onboard(company: str, trigger: str) -> int:
        seen.append(("onboard", company, trigger))
        return 0

    monkeypatch.setattr(cli, "run_ax_command", fake_ax)
    monkeypatch.setattr(cli, "onboard_command", fake_onboard)
    cli.main(["run-ax", "--company", "kemira", "--mode", "dev", "--trigger", "schedule"])
    cli.main(["onboard", "--company", "kemira"])
    assert seen == [("ax", "kemira", "dev", "schedule"), ("onboard", "kemira", "manual")]


# ---- local runner --------------------------------------------------------------------------


class FakeProcess:
    def __init__(self) -> None:
        self.code: int | None = None

    def poll(self) -> int | None:
        return self.code


class Spawner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path]] = []
        self.processes: list[FakeProcess] = []
        self.fail = False

    def __call__(self, command: list[str], log_file: Path) -> FakeProcess:
        if self.fail:
            raise OSError(2, "No such file")
        self.calls.append((command, log_file))
        self.processes.append(FakeProcess())
        return self.processes[-1]


async def test_local_runner_starts_the_dispatcher_in_the_background() -> None:
    spawner = Spawner()
    started = await LocalJobRunner(spawner).start("ax", "kemira")
    ((command, log_file),) = spawner.calls
    assert command == [sys.executable, "-m", "app.cli", *job_args("ax", "kemira")]
    assert log_file.parent == runner.LOG_DIR and log_file.name.startswith("ax-kemira-")
    assert (started.runner, started.status, started.job) == ("local", "started", "ax")
    assert "log:" in started.detail


async def test_local_runner_knows_a_running_job_and_a_finished_one() -> None:
    spawner = Spawner()
    local = LocalJobRunner(spawner)
    await local.start("ax", "kemira")
    assert local.is_running("ax", "kemira")
    assert not local.is_running("onboard", "kemira") and not local.is_running("ax", "other")
    with pytest.raises(JobAlreadyRunning):
        await local.start("ax", "kemira")
    spawner.processes[0].code = 0  # the process ended
    assert not local.is_running("ax", "kemira")
    await local.start("ax", "kemira")
    assert len(spawner.calls) == 2


async def test_local_runner_turns_os_errors_into_a_clear_message() -> None:
    spawner = Spawner()
    spawner.fail = True
    with pytest.raises(JobStartError, match="could not start the local process"):
        await LocalJobRunner(spawner).start("ax", "kemira")


# ---- GitHub runner -------------------------------------------------------------------------


def github_settings(**values: str) -> SimpleNamespace:
    base = {
        "github_repo": "me/answerwatch",
        "github_dispatch_token": TOKEN,
        "github_ref": "main",
        "job_runner": "github",
    }
    return SimpleNamespace(**(base | values))


def github_runner(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response | Exception, **settings: str
) -> tuple[GithubJobRunner, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(runner, "get_settings", lambda: github_settings(**settings))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GithubJobRunner(client), seen


async def test_github_runner_dispatches_the_agents_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh, seen = github_runner(monkeypatch, httpx.Response(204))
    started = await gh.start("ax", "kemira")
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == (
        "https://api.github.com/repos/me/answerwatch/actions/workflows/agents.yml/dispatches"
    )
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["accept"] == "application/vnd.github+json"
    assert request.headers["x-github-api-version"] == "2026-03-10"
    assert json.loads(request.content) == {
        "ref": "main",
        "inputs": {"job": "ax", "company": "kemira"},
    }
    assert (started.runner, started.status) == ("github", "started")
    assert TOKEN not in started.model_dump_json()


async def test_faq_source_dispatch_sends_question_as_workflow_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "get_settings", lambda: github_settings())
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        workflow = await dispatch_faq_source_update(
            "kemira", "Which water question should be added?", client=client
        )
    (request,) = seen
    assert workflow == "update-faq-source.yml"
    assert str(request.url) == (
        "https://api.github.com/repos/me/answerwatch/actions/workflows/"
        "update-faq-source.yml/dispatches"
    )
    assert json.loads(request.content) == {
        "ref": "main",
        "inputs": {"company": "kemira", "question": "Which water question should be added?"},
    }


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(401, json={"message": "bad token"}), "GITHUB_DISPATCH_TOKEN"),
        (httpx.Response(404, json={"message": "missing"}), "update-faq-source.yml"),
    ],
)
async def test_faq_source_dispatch_reports_github_failures(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response, message: str
) -> None:
    gh, _ = github_runner(monkeypatch, response)
    client = gh._client
    assert client is not None
    monkeypatch.setattr(runner, "get_settings", lambda: github_settings())
    with pytest.raises(JobStartError, match=message):
        await dispatch_faq_source_update("kemira", "A valid public question?", client=client)


async def test_github_runner_accepts_a_200_with_run_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh, _ = github_runner(monkeypatch, httpx.Response(200, json={"workflow_run_id": 7}))
    assert (await gh.start("onboard", "kemira")).status == "started"


async def test_github_runner_uses_the_configured_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    gh, seen = github_runner(monkeypatch, httpx.Response(204), github_ref="release")
    await gh.start("ax", "kemira")
    assert json.loads(seen[0].content)["ref"] == "release"


@pytest.mark.parametrize(
    ("status", "hint"),
    [
        (401, "token was rejected"),
        (403, "Actions: read and write"),
        (404, "repository or workflow not found"),
        (422, "workflow_dispatch"),
        (500, "unexpected answer"),
    ],
)
async def test_github_errors_become_readable_messages_without_the_token(
    monkeypatch: pytest.MonkeyPatch, status: int, hint: str
) -> None:
    gh, _ = github_runner(monkeypatch, httpx.Response(status, json={"message": "Bad credentials"}))
    with pytest.raises(JobStartError) as info:
        await gh.start("ax", "kemira")
    message = str(info.value)
    assert f"GitHub answered {status}" in message and hint in message
    assert "Bad credentials" in message and TOKEN not in message


async def test_github_network_errors_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    gh, _ = github_runner(monkeypatch, httpx.ConnectError("boom"))
    with pytest.raises(JobStartError, match="could not reach GitHub: ConnectError"):
        await gh.start("ax", "kemira")


async def test_github_runner_needs_a_token_and_a_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    gh, seen = github_runner(monkeypatch, httpx.Response(204), github_dispatch_token="")
    with pytest.raises(JobStartError, match="GITHUB_DISPATCH_TOKEN is not set"):
        await gh.start("ax", "kemira")
    gh, seen = github_runner(monkeypatch, httpx.Response(204), github_repo="your-user/answerwatch")
    with pytest.raises(JobStartError, match="GITHUB_REPO is not set"):
        await gh.start("ax", "kemira")
    assert seen == []  # nothing was sent


def test_github_error_survives_a_non_json_body() -> None:
    assert "GitHub answered 502" in github_error(httpx.Response(502, text="<html>bad gateway"))


# ---- choosing the runner and start_job -----------------------------------------------------


def test_get_job_runner_follows_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "_runner", None)
    monkeypatch.setattr(runner, "get_settings", lambda: SimpleNamespace(job_runner="local"))
    assert runner.get_job_runner().name == "local"
    assert runner.get_job_runner() is runner.get_job_runner()  # one instance
    monkeypatch.setattr(runner, "get_settings", lambda: SimpleNamespace(job_runner="github"))
    assert runner.get_job_runner().name == "github"


class NoDb:
    """start_job only reads the database for ax / onboard; these tests never reach it."""


async def test_start_job_refuses_jobs_that_are_not_built(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(JOBS, "faq", registry.Job(None))
    with pytest.raises(JobNotAvailable, match="Job 'faq' is not available yet"):
        await start_job(NoDb(), LocalJobRunner(Spawner()), "faq", "kemira")  # type: ignore[arg-type]
