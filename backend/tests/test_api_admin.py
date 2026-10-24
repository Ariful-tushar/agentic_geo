from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Answer, Company, Question, Run
from tests.api_helpers import ADMIN, PASSWORD, Api, api, seeded  # noqa: F401
from tests.email_helpers import RECIPIENTS, set_contacts
from tests.kb_helpers import KEMIRA

YAML = KEMIRA.read_text(encoding="utf-8")


def profile_json() -> dict[str, Any]:
    from app.profiles.loader import load_profile_file

    data = load_profile_file(KEMIRA).model_dump(mode="json")
    data.update(id="demo", name="Demo Oy")
    return data


# ---- login and the admin token -------------------------------------------------------------


def test_login_with_the_right_password(api: Api) -> None:
    response = api.send("POST", "/api/admin/login", json={"password": PASSWORD})
    assert response.status_code == 200 and response.json() == {"ok": True}


@pytest.mark.parametrize("password", ["wrong", "", PASSWORD + " ", PASSWORD.upper()])
def test_login_with_a_wrong_password(api: Api, password: str) -> None:
    response = api.send("POST", "/api/admin/login", json={"password": password})
    assert response.status_code == 401 and response.json()["detail"] == "Wrong password"


def test_login_needs_a_body(api: Api) -> None:
    assert api.send("POST", "/api/admin/login", json={}).status_code == 422


ADMIN_CALLS = [
    ("PATCH", "/api/companies/kemira/settings", {"monitoring_enabled": False}),
    ("POST", "/api/companies/kemira/jobs", {"job": "ax"}),
    ("POST", "/api/companies", None),
    ("POST", "/api/companies/import", {"yaml": "id: x"}),
]


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_CALLS)
@pytest.mark.parametrize("headers", [{}, {"X-Admin-Token": "wrong"}, {"X-Admin-Token": ""}])
def test_write_endpoints_need_the_admin_token(
    api: Api, method: str, path: str, body: Any, headers: dict[str, str]
) -> None:
    seeded(api)
    response = api.send(
        method, path, json=body if body is not None else profile_json(), headers=headers
    )
    assert response.status_code == 401
    assert "X-Admin-Token" in response.json()["detail"]
    assert api.runner.started == []  # nothing happened


def test_an_empty_admin_password_means_nobody_is_admin(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from app.api import auth

    seeded(api)
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(admin_password=""))
    response = api.send(
        "PATCH", "/api/companies/kemira/settings", json={}, headers={"X-Admin-Token": ""}
    )
    assert response.status_code == 401
    assert api.send("POST", "/api/admin/login", json={"password": ""}).status_code == 401


# ---- settings ------------------------------------------------------------------------------


def test_settings_update_is_partial_and_saved(api: Api) -> None:
    seeded(api)
    response = api.send(
        "PATCH", "/api/companies/kemira/settings", json={"monitoring_enabled": False}, headers=ADMIN
    )
    body = response.json()
    assert response.status_code == 200
    assert (body["monitoring_enabled"], body["emails_enabled"]) == (False, True)
    detail = api.get("/api/companies/kemira").json()
    assert detail["monitoring_enabled"] is False and detail["emails_enabled"] is True

    api.send(
        "PATCH",
        "/api/companies/kemira/settings",
        json={"emails_enabled": False, "contact_emails": ["a@example.org", "b@example.org"]},
        headers=ADMIN,
    )
    admin = api.get("/api/companies/kemira", headers=ADMIN).json()
    assert admin["emails_enabled"] is False and admin["monitoring_enabled"] is False
    assert admin["contact_emails"] == ["a@example.org", "b@example.org"]
    assert api.get("/api/companies/kemira").json()["contact_email_count"] == 2


def test_settings_reject_bad_emails_and_unknown_companies(api: Api) -> None:
    seeded(api)
    bad = api.send(
        "PATCH",
        "/api/companies/kemira/settings",
        json={"contact_emails": ["not-an-email"]},
        headers=ADMIN,
    )
    assert bad.status_code == 422
    missing = api.send("PATCH", "/api/companies/nope/settings", json={}, headers=ADMIN)
    assert missing.status_code == 404


# ---- jobs ----------------------------------------------------------------------------------


@pytest.mark.parametrize("job", ["ax", "onboard", "competitor"])
def test_available_jobs_are_started_through_the_runner(api: Api, job: str) -> None:
    seeded(api)
    response = api.send("POST", "/api/companies/kemira/jobs", json={"job": job}, headers=ADMIN)
    assert response.status_code == 202
    assert response.json() == {
        "job": job,
        "company_id": "kemira",
        "runner": "fake",
        "status": "started",
        "detail": "fake",
    }
    assert api.runner.started == [(job, "kemira")]


@pytest.mark.parametrize("job", ["faq"])
def test_jobs_that_are_not_built_yet_answer_501(api: Api, job: str) -> None:
    seeded(api)
    response = api.send("POST", "/api/companies/kemira/jobs", json={"job": job}, headers=ADMIN)
    assert response.status_code == 501
    assert response.json()["detail"] == f"Job '{job}' is not available yet"
    assert api.runner.started == []


def test_unknown_job_and_company(api: Api) -> None:
    seeded(api)
    assert (
        api.send("POST", "/api/companies/kemira/jobs", json={"job": "rm -rf"}, headers=ADMIN)
    ).status_code == 422
    assert (
        api.send("POST", "/api/companies/nope/jobs", json={"job": "ax"}, headers=ADMIN)
    ).status_code == 404


def test_a_job_that_is_already_running_answers_409(api: Api) -> None:
    seeded(api)
    api.runner.busy = True  # the runner knows of a running process
    response = api.send("POST", "/api/companies/kemira/jobs", json={"job": "ax"}, headers=ADMIN)
    assert response.status_code == 409
    assert "already running" in response.json()["detail"]


async def _add_running_run(session: AsyncSession, hours_ago: float) -> None:
    started = datetime.now(UTC) - timedelta(hours=hours_ago)
    session.add(
        Run(
            company_id="kemira",
            kind="ax",
            run_date=date(2026, 11, 1),  # a day without a seeded run
            mode="live",
            status="running",
            trigger="manual",
            started_at=started,
            details={},
        )
    )
    await session.commit()


def test_a_running_ax_run_in_the_database_blocks_a_new_one(api: Api) -> None:
    seeded(api)

    async def go(session: AsyncSession) -> None:
        await _add_running_run(session, 0.1)

    api.with_session(go)
    response = api.send("POST", "/api/companies/kemira/jobs", json={"job": "ax"}, headers=ADMIN)
    assert response.status_code == 409 and "already running" in response.json()["detail"]
    # a different job for the same company is not blocked by it
    assert (
        api.send(
            "POST", "/api/companies/kemira/jobs", json={"job": "onboard"}, headers=ADMIN
        ).status_code
        == 202
    )


def test_a_stale_running_run_does_not_block(api: Api) -> None:
    seeded(api)

    async def go(session: AsyncSession) -> None:
        await _add_running_run(session, 5)  # older than 3 hours: crashed

    api.with_session(go)
    response = api.send("POST", "/api/companies/kemira/jobs", json={"job": "ax"}, headers=ADMIN)
    assert response.status_code == 202


def test_a_dev_run_does_not_block_a_live_job(api: Api) -> None:
    seeded(api)

    async def go(session: AsyncSession) -> None:
        await _add_running_run(session, 0.1)
        run = await session.scalar(select(Run).where(Run.status == "running"))
        run.mode = "dev"
        await session.commit()

    api.with_session(go)
    assert (
        api.send(
            "POST", "/api/companies/kemira/jobs", json={"job": "ax"}, headers=ADMIN
        ).status_code
        == 202
    )


def test_onboarding_in_progress_blocks_another_onboard(api: Api) -> None:
    seeded(api)

    async def go(session: AsyncSession) -> None:
        (await session.get(Company, "kemira")).onboarding_status = "building"
        await session.commit()

    api.with_session(go)
    response = api.send(
        "POST", "/api/companies/kemira/jobs", json={"job": "onboard"}, headers=ADMIN
    )
    assert response.status_code == 409
    assert (
        api.send(
            "POST", "/api/companies/kemira/jobs", json={"job": "ax"}, headers=ADMIN
        ).status_code
        == 202
    )


def test_a_runner_failure_answers_502_with_the_reason(api: Api) -> None:
    seeded(api)
    api.runner.error = "GITHUB_DISPATCH_TOKEN is not set"
    response = api.send("POST", "/api/companies/kemira/jobs", json={"job": "ax"}, headers=ADMIN)
    assert response.status_code == 502
    assert response.json()["detail"] == (
        "Could not start the job: GITHUB_DISPATCH_TOKEN is not set"
    )


# ---- create and import a profile -----------------------------------------------------------


def counts(api: Api) -> dict[str, int]:
    async def go(session: AsyncSession) -> dict[str, int]:
        return {
            "companies": await session.scalar(select(func.count()).select_from(Company)),
            "questions": await session.scalar(select(func.count()).select_from(Question)),
            "answers": await session.scalar(select(func.count()).select_from(Answer)),
        }

    return api.with_session(go)


def test_create_company_saves_the_profile_and_starts_onboarding(api: Api) -> None:
    response = api.send("POST", "/api/companies", json=profile_json(), headers=ADMIN)
    body = response.json()
    assert response.status_code == 201
    assert (body["company_id"], body["created"], body["questions_added"]) == ("demo", True, 24)
    assert body["job"]["job"] == "onboard" and body["job_error"] is None
    assert api.runner.started == [("onboard", "demo")]
    assert counts(api)["questions"] == 24
    assert api.get("/api/companies/demo").json()["name"] == "Demo Oy"


def test_create_company_twice_answers_409_and_changes_nothing(api: Api) -> None:
    api.send("POST", "/api/companies", json=profile_json(), headers=ADMIN)
    before = counts(api)
    again = api.send("POST", "/api/companies", json=profile_json(), headers=ADMIN)
    assert again.status_code == 409 and "already exists" in again.json()["detail"]
    assert counts(api) == before and len(api.runner.started) == 1


def test_create_company_validates_the_profile(api: Api) -> None:
    data = profile_json()
    data["fact_questions"] = []
    response = api.send("POST", "/api/companies", json=data, headers=ADMIN)
    assert response.status_code == 422
    assert counts(api)["companies"] == 0


def test_import_yaml_is_create_or_update_and_adds_nothing_the_second_time(api: Api) -> None:
    first = api.send("POST", "/api/companies/import", json={"yaml": YAML}, headers=ADMIN)
    assert first.status_code == 200
    assert (first.json()["created"], first.json()["questions_added"]) == (True, 24)
    snapshot = counts(api)

    second = api.send("POST", "/api/companies/import", json={"yaml": YAML}, headers=ADMIN)
    body = second.json()
    assert second.status_code == 200
    assert (body["created"], body["questions_added"], body["questions_kept"]) == (False, 0, 24)
    assert (body["competitors_added"], body["sources_added"]) == (0, 0)
    assert counts(api) == snapshot
    assert api.runner.started == [("onboard", "kemira"), ("onboard", "kemira")]


def test_import_yaml_errors_are_readable(api: Api) -> None:
    bad_yaml = api.send("POST", "/api/companies/import", json={"yaml": "a: [1"}, headers=ADMIN)
    assert bad_yaml.status_code == 422 and "Invalid YAML" in bad_yaml.json()["detail"]
    invalid = api.send(
        "POST", "/api/companies/import", json={"yaml": "id: x\nname: X"}, headers=ADMIN
    )
    assert invalid.status_code == 422
    assert "validation error" in invalid.json()["detail"]
    empty = api.send("POST", "/api/companies/import", json={"yaml": ""}, headers=ADMIN)
    assert empty.status_code == 422
    assert counts(api)["companies"] == 0


def test_the_profile_stays_saved_when_the_onboarding_job_cannot_start(api: Api) -> None:
    api.runner.error = "no token"
    response = api.send("POST", "/api/companies/import", json={"yaml": YAML}, headers=ADMIN)
    body = response.json()
    assert response.status_code == 200
    assert body["job"] is None and "no token" in body["job_error"]
    assert counts(api)["questions"] == 24


def test_import_while_onboarding_runs_reports_it_in_job_error(api: Api) -> None:
    api.send("POST", "/api/companies/import", json={"yaml": YAML}, headers=ADMIN)
    api.runner.busy = True
    body = api.send("POST", "/api/companies/import", json={"yaml": YAML}, headers=ADMIN).json()
    assert body["job"] is None and "already running" in body["job_error"]


# ---- emails (D3.3) ---------------------------------------------------------------------------


def test_test_email_needs_the_admin_token(api: Api) -> None:
    seeded(api)
    assert api.send("POST", "/api/companies/kemira/test-email").status_code == 401
    assert api.sender.sent == []


def test_test_email_is_sent_and_logged(api: Api) -> None:
    seeded(api)
    api.with_session(lambda s: set_contacts(s, RECIPIENTS, enabled=False))  # switch is ignored

    response = api.send("POST", "/api/companies/kemira/test-email", headers=ADMIN)

    assert response.status_code == 200 and response.json() == {"status": "sent", "detail": ""}
    assert api.sender.sent[0][0] == RECIPIENTS
    log = api.get("/api/companies/kemira/emails", headers=ADMIN).json()
    assert [(e["kind"], e["status"]) for e in log] == [("test", "sent")]


def test_test_email_reports_a_failure_without_a_server_error(api: Api) -> None:
    seeded(api)
    api.with_session(lambda s: set_contacts(s, RECIPIENTS))
    api.sender.error = ConnectionError("smtp down")

    response = api.send("POST", "/api/companies/kemira/test-email", headers=ADMIN)

    assert response.status_code == 200 and response.json()["status"] == "failed"
    assert "smtp down" in response.json()["detail"]


def test_test_email_without_recipients_says_so(api: Api) -> None:
    seeded(api)
    api.with_session(lambda s: set_contacts(s, []))
    body = api.send("POST", "/api/companies/kemira/test-email", headers=ADMIN).json()
    assert body == {"status": "skipped", "detail": "no recipients"}


def test_test_email_for_an_unknown_company_is_404(api: Api) -> None:
    assert api.send("POST", "/api/companies/nope/test-email", headers=ADMIN).status_code == 404


def test_the_daily_job_can_be_started_and_an_ax_run_blocks_it(api: Api) -> None:
    seeded(api)
    ok = api.send("POST", "/api/companies/kemira/jobs", json={"job": "daily"}, headers=ADMIN)
    assert ok.status_code == 202 and api.runner.started == [("daily", "kemira")]

    async def running(s: AsyncSession) -> None:
        from tests.api_helpers import add_run

        await add_run(s, date(2026, 10, 22), "live", status="running")
        run = (await s.scalars(select(Run).where(Run.status == "running"))).one()
        run.started_at = datetime.now(UTC)
        await s.commit()

    api.with_session(running)
    blocked = api.send("POST", "/api/companies/kemira/jobs", json={"job": "daily"}, headers=ADMIN)
    assert blocked.status_code == 409


def test_reimport_keeps_the_real_contact_emails(api: Api) -> None:
    """The seed has a placeholder address; importing it again must not overwrite the real one."""
    api.send("POST", "/api/companies/import", json={"yaml": YAML}, headers=ADMIN)
    api.send(
        "PATCH",
        "/api/companies/kemira/settings",
        json={"contact_emails": ["real@example.org"]},
        headers=ADMIN,
    )

    again = api.send("POST", "/api/companies/import", json={"yaml": YAML}, headers=ADMIN)

    assert again.status_code == 200 and again.json()["created"] is False
    company = api.get("/api/companies/kemira", headers=ADMIN).json()
    assert company["contact_emails"] == ["real@example.org"]
