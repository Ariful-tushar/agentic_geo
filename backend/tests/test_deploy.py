"""Deployment files: CORS origins, engines file location, the agents workflow."""

import pytest
import yaml

from app import cli
from app.config import BACKEND_DIR, Settings
from app.jobs import registry
from app.llm.engines import load_engines

REPO_ROOT = BACKEND_DIR.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "agents.yml"


def test_frontend_origin_may_list_several_origins() -> None:
    settings = Settings(frontend_origin="https://a.vercel.app/, http://localhost:5173 ,")
    assert settings.allowed_origins == ["https://a.vercel.app", "http://localhost:5173"]


def test_the_engines_file_is_inside_backend_so_the_docker_image_has_it() -> None:
    path = Settings().engines_file
    assert path == BACKEND_DIR / "config" / "engines.yaml"
    assert path.is_file()
    assert {e.id for e in load_engines()} >= {"groq_web", "gemini_memory"}


def test_the_dockerfile_copies_the_whole_backend_folder() -> None:
    assert "COPY . ." in (BACKEND_DIR / "Dockerfile").read_text(encoding="utf-8")


def load_workflow() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))  # YAML reads the key `on` as True
    return data


def test_workflow_scans_faq_hourly_and_keeps_the_daily_schedule() -> None:
    triggers = load_workflow()["on"]
    assert "push" not in triggers
    assert triggers["schedule"] == [
        {"cron": "0 * * * *", "timezone": "Europe/Helsinki"},
        {"cron": "15 7 * * *", "timezone": "Europe/Helsinki"},
    ]
    assert set(triggers["workflow_dispatch"]["inputs"]) == {"job", "company"}
    env = next(
        step["env"]
        for step in load_workflow()["jobs"]["run"]["steps"]
        if step.get("name") == "Run the job"
    )
    hourly_faq_job = (
        "github.event_name == 'schedule' && github.event.schedule == '0 * * * *' && 'faq'"
    )
    assert hourly_faq_job in env["JOB"]
    assert "github.event_name == 'push'" not in env["JOB"] + env["COMPANY"]


def test_workflow_input_help_names_every_job() -> None:
    description = load_workflow()["on"]["workflow_dispatch"]["inputs"]["job"]["description"]
    assert set(description.split(" | ")) == set(registry.JOBS)


def test_workflow_calls_the_job_dispatcher_and_leaves_out_an_empty_company() -> None:
    steps = load_workflow()["jobs"]["run"]["steps"]
    run_step = next(s for s in steps if "app.cli" in s.get("run", ""))
    assert 'app.cli "${args[@]}"' in run_step["run"]
    assert "args=(job" in run_step["run"]
    assert '[ -n "$COMPANY" ]' in run_step["run"]
    # inputs reach the shell only through env vars
    assert "inputs" not in run_step["run"]
    assert {"JOB", "COMPANY", "TRIGGER", "DATABASE_URL"} <= set(run_step["env"])


def test_workflow_gets_every_secret_the_daily_job_needs() -> None:
    env = next(s for s in load_workflow()["jobs"]["run"]["steps"] if "env" in s)["env"]
    for name in (
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "SMTP_USER",
        "SMTP_APP_PASSWORD",
        "DASHBOARD_URL",
    ):
        assert env[name] == f"${{{{ secrets.{name} }}}}"


def test_job_daily_without_company_runs_every_company(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str | None, str]] = []

    async def handler(company: str | None, trigger: str, mode: str) -> int:
        seen.append((company, trigger))
        return 0

    monkeypatch.setitem(registry.JOBS, "daily", registry.Job(handler, needs_company=False))
    assert cli.main(["job", "daily", "--trigger", "schedule"]) == 0
    assert seen == [(None, "schedule")]


def test_the_seed_profile_keeps_a_placeholder_email() -> None:
    seed = (REPO_ROOT / "seed" / "kemira.profile.yaml").read_text(encoding="utf-8")
    assert "YOUR_EMAIL@gmail.com" in seed
    assert seed.count("@gmail.com") == 1  # only the placeholder, never a real address
