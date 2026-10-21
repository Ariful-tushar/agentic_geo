import pytest

from tests.api_helpers import ADMIN, D1, D2, Api, api, new_id, seeded  # noqa: F401

# ---- engines and companies -----------------------------------------------------------------


def test_engines_lists_the_tested_engines_and_rag(api: Api) -> None:
    body = (api.get("/api/engines")).json()
    by_id = {e["id"]: e for e in body}
    assert list(by_id) == ["groq_web", "gemini_memory", "openrouter_memory", "rag"]
    assert by_id["groq_web"]["web_search"] is True
    assert by_id["gemini_memory"]["web_search"] is False
    assert by_id["openrouter_memory"]["enabled"] is False
    assert by_id["rag"] == {
        "id": "rag",
        "label": "Our RAG on the company's own pages",
        "web_search": False,
        "enabled": True,
    }
    assert all(e["label"] for e in body)


def test_companies_list_shows_the_last_live_run_only(api: Api) -> None:
    ids = seeded(api)
    (company,) = (api.get("/api/companies")).json()
    assert company["id"] == "kemira" and company["monitoring_enabled"] is True
    assert company["onboarding_status"] == "pending"
    run = company["last_run"]
    assert (run["mode"], run["run_date"], run["id"]) == ("live", str(D2), str(ids["live2"]))
    assert run["summary"] == {"answers_ok": 3, "warnings": ["a warning"]}  # nothing else leaks


def test_companies_list_is_empty_without_companies(api: Api) -> None:
    assert (api.get("/api/companies")).json() == []


def test_company_detail_has_profile_questions_competitors_and_sources(api: Api) -> None:
    seeded(api)
    body = (api.get("/api/companies/kemira")).json()
    assert body["name"] == "Kemira" and "Kemira Oyj" in body["aliases"]
    assert len(body["questions"]) == 24
    assert {q["kind"] for q in body["questions"]} == {"fact", "generic"}
    employees = next(q for q in body["questions"] if q["expected_value"] == 4900)
    assert (employees["tolerance"], employees["unit"]) == (100, "people")
    assert {c["name"] for c in body["competitors"]} >= {"Ecolab", "Solenis", "SNF", "Kurita"}
    assert len(body["knowledge_sources"]) == 9
    assert body["last_run"]["mode"] == "live"


def test_contact_emails_are_hidden_unless_admin(api: Api) -> None:
    seeded(api)
    public = (api.get("/api/companies/kemira")).json()
    assert public["contact_emails"] is None
    assert public["contact_email_count"] >= 1
    wrong = api.get("/api/companies/kemira", headers={"X-Admin-Token": "nope"})
    assert wrong.status_code == 200 and wrong.json()["contact_emails"] is None  # not an error
    admin = (api.get("/api/companies/kemira", headers=ADMIN)).json()
    assert len(admin["contact_emails"]) == admin["contact_email_count"]
    assert "@" in admin["contact_emails"][0]


@pytest.mark.parametrize(
    "path",
    [
        "/api/companies/nope",
        "/api/companies/nope/accuracy/trend",
        "/api/companies/nope/accuracy/today",
        "/api/companies/nope/accuracy/details?engine=rag",
        "/api/companies/nope/alerts",
        "/api/companies/nope/runs",
    ],
)
def test_unknown_company_is_404(api: Api, path: str) -> None:
    response = api.get(path)
    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


# ---- accuracy ------------------------------------------------------------------------------


def test_trend_returns_live_points_only(api: Api) -> None:
    seeded(api)
    points = (api.get("/api/companies/kemira/accuracy/trend?days=7")).json()
    assert [(p["date"], p["engine"], p["accuracy"]) for p in points] == [
        (str(D1), "groq_web", 0.667),
        (str(D1), "rag", 1.0),
        (str(D2), "groq_web", 0.5),
        (str(D2), "rag", 1.0),
    ]
    assert "gemini_memory" not in {p["engine"] for p in points}  # only had a dev row
    assert 0.123 not in {p["accuracy"] for p in points}


def test_trend_days_limits_the_window(api: Api) -> None:
    seeded(api)
    one = (api.get("/api/companies/kemira/accuracy/trend?days=1")).json()
    assert {p["date"] for p in one} == {str(D2)}  # "today" is D2
    default = (api.get("/api/companies/kemira/accuracy/trend")).json()
    assert len(default) == 4


@pytest.mark.parametrize("days", [0, -1, 366, "x"])
def test_trend_rejects_bad_days(api: Api, days: object) -> None:
    seeded(api)
    response = api.get(f"/api/companies/kemira/accuracy/trend?days={days}")
    assert response.status_code == 422


def test_today_gives_latest_previous_and_delta(api: Api) -> None:
    seeded(api)
    items = {i["engine"]: i for i in (api.get("/api/companies/kemira/accuracy/today")).json()}
    assert set(items) == {"groq_web", "rag"}  # the dev-only engine is not there
    assert items["groq_web"] == {
        "engine": "groq_web",
        "date": str(D2),
        "accuracy": 0.5,
        "n_questions": 2,
        "previous_date": str(D1),
        "previous_accuracy": 0.667,
        "delta": pytest.approx(-0.167),
    }
    assert items["rag"]["delta"] == 0.0


def test_today_with_no_data_is_empty(api: Api) -> None:
    seeded(api)
    api.with_session(_delete_accuracy)
    assert (api.get("/api/companies/kemira/accuracy/today")).json() == []


async def _delete_accuracy(session) -> None:  # noqa: ANN001
    from sqlalchemy import delete

    from app.db.models import DailyAccuracy

    await session.execute(delete(DailyAccuracy))
    await session.commit()


def test_details_matrix(api: Api) -> None:
    ids = seeded(api)
    body = (api.get("/api/companies/kemira/accuracy/details?engine=groq_web")).json()
    assert body["engine"] == "groq_web"
    assert (body["date_from"], body["date_to"]) == ("2026-10-08", str(D2))
    assert body["dates"] == [str(D1), str(D2)]
    rows = {r["code"]: r for r in body["rows"]}
    assert len(rows) == 18  # every fact question is a row, answered or not
    q01 = rows["Q01"]["cells"]
    assert q01[str(D1)]["status"] == "scored" and q01[str(D1)]["verdict"] == "correct"
    assert q01[str(D2)]["verdict"] == "wrong" and q01[str(D2)]["answer_id"] == str(ids["a2"])
    assert q01[str(D2)]["score"] == 0.0
    assert rows["Q04"]["cells"][str(D1)]["status"] == "error"  # shown grey in the dashboard
    assert "verdict" not in {k for k, v in rows["Q04"]["cells"][str(D1)].items() if v}
    assert rows["Q05"]["cells"] == {}
    assert all(r["text"] for r in rows.values())


def test_details_never_contains_dev_answers(api: Api) -> None:
    ids = seeded(api)
    body = (api.get("/api/companies/kemira/accuracy/details?engine=groq_web")).json()
    answer_ids = {c["answer_id"] for r in body["rows"] for c in r["cells"].values()}
    assert str(ids["dev"]) not in answer_ids


def test_details_from_and_to(api: Api) -> None:
    seeded(api)
    url = f"/api/companies/kemira/accuracy/details?engine=groq_web&from={D2}&to={D2}"
    body = (api.get(url)).json()
    assert body["dates"] == [str(D2)]
    only_old = f"/api/companies/kemira/accuracy/details?engine=rag&from={D1}&to={D1}"
    assert (api.get(only_old)).json()["dates"] == [str(D1)]


@pytest.mark.parametrize(
    "query",
    [
        "",  # engine is required
        "engine=nope",
        f"engine=rag&from={D2}&to={D1}",
        "engine=rag&from=2020-01-01&to=2026-10-21",
        "engine=rag&from=not-a-date",
    ],
)
def test_details_rejects_bad_queries(api: Api, query: str) -> None:
    seeded(api)
    response = api.get(f"/api/companies/kemira/accuracy/details?{query}")
    assert response.status_code == 422


# ---- one answer ----------------------------------------------------------------------------


def test_answer_detail_has_everything_for_the_side_panel(api: Api) -> None:
    ids = seeded(api)
    body = (api.get(f"/api/answers/{ids['a2']}")).json()
    assert body["engine"] == "groq_web" and body["run_date"] == str(D2)
    assert body["question"]["code"] == "Q01"
    assert body["question"]["expected_answer"]
    assert body["text"] == "Espoo, Finland." and body["error"] is None
    assert body["score"] == {
        "verdict": "wrong",
        "score": 0.0,
        "reason": "reason wrong",
        "quote": "Espoo, Finland.",
        "quote_verified": True,
        "method": "judge",
    }
    assert body["citations"] == [
        {
            "url": "https://news.example.org/hq",
            "title": "HQ news",
            "domain": "news.example.org",
            "owner": "third_party",
        }
    ]
    assert body["why"] == {
        "source_type": "cited_page",
        "source_url": "https://news.example.org/hq",
        "evidence_quote": "Kemira is based in Espoo.",
        "explanation": "The page says Espoo.",
        "suggested_fix": "Ask the publisher to correct it.",
    }
    assert body["previous"] == {
        "answer_id": str(ids["a1"]),
        "run_date": str(D1),
        "text": "Helsinki, Finland.",
        "verdict": "correct",
        "score": 1.0,
    }
    assert "raw_json" not in body and "raw" not in str(body)


def test_the_first_answer_has_no_previous_one_and_may_have_no_why(api: Api) -> None:
    ids = seeded(api)
    body = (api.get(f"/api/answers/{ids['a1']}")).json()
    assert body["previous"] is None and body["why"] is None and body["citations"] == []


def test_an_errored_answer_shows_its_error_and_no_score(api: Api) -> None:
    ids = seeded(api)
    details = (api.get("/api/companies/kemira/accuracy/details?engine=groq_web")).json()
    errored = next(r for r in details["rows"] if r["code"] == "Q04")["cells"][str(D1)]
    body = (api.get(f"/api/answers/{errored['answer_id']}")).json()
    assert body["error"] == "ConnectionError: down" and body["text"] is None
    assert body["score"] is None
    assert ids  # seeded


def test_dev_and_unknown_answers_are_404_and_bad_ids_422(api: Api) -> None:
    ids = seeded(api)
    assert (api.get(f"/api/answers/{ids['dev']}")).status_code == 404
    assert (api.get(f"/api/answers/{new_id()}")).status_code == 404
    assert (api.get("/api/answers/not-a-uuid")).status_code == 422


# ---- alerts and runs -----------------------------------------------------------------------


def test_alerts_link_the_before_and_after_answers(api: Api) -> None:
    ids = seeded(api)
    (alert,) = (api.get("/api/companies/kemira/alerts")).json()
    assert alert["kind"] == "score_drop" and alert["severity"] == "warning"
    assert alert["engine"] == "groq_web" and alert["question_code"] == "Q01"
    assert alert["question_text"] and "got worse" in alert["summary"]
    assert (alert["before_answer_id"], alert["after_answer_id"]) == (str(ids["a1"]), str(ids["a2"]))
    assert alert["run_date"] == str(D2)


@pytest.mark.parametrize("days", [0, 366])
def test_alerts_reject_bad_days(api: Api, days: int) -> None:
    seeded(api)
    assert (api.get(f"/api/companies/kemira/alerts?days={days}")).status_code == 422


def test_runs_are_live_only_newest_first(api: Api) -> None:
    ids = seeded(api)
    runs = (api.get("/api/companies/kemira/runs")).json()
    assert [r["run_date"] for r in runs] == [str(D2), str(D1)]
    assert {r["mode"] for r in runs} == {"live"}
    assert str(ids["dev_run"]) not in {r["id"] for r in runs}
    assert len((api.get("/api/companies/kemira/runs?limit=1")).json()) == 1
    assert (api.get("/api/companies/kemira/runs?limit=0")).status_code == 422
    assert (api.get("/api/companies/kemira/runs?limit=101")).status_code == 422


def test_every_read_endpoint_is_public(api: Api) -> None:
    ids = seeded(api)
    for path in (
        "/api/health",
        "/api/engines",
        "/api/companies",
        "/api/companies/kemira",
        "/api/companies/kemira/accuracy/trend",
        "/api/companies/kemira/accuracy/today",
        "/api/companies/kemira/accuracy/details?engine=rag",
        f"/api/answers/{ids['a1']}",
        "/api/companies/kemira/alerts",
        "/api/companies/kemira/runs",
    ):
        assert (api.get(path)).status_code == 200, path


def test_email_log_hides_recipients_unless_admin(api: Api) -> None:
    from tests.email_helpers import RECIPIENTS, set_contacts

    seeded(api)
    api.with_session(lambda s: set_contacts(s, RECIPIENTS))
    api.send("POST", "/api/companies/kemira/test-email", headers=ADMIN)

    public = api.get("/api/companies/kemira/emails").json()
    assert len(public) == 1
    assert public[0]["recipients"] is None and public[0]["recipient_count"] == 2
    assert (public[0]["kind"], public[0]["status"]) == ("test", "sent")
    assert "@" not in str(public)
    admin = api.get("/api/companies/kemira/emails", headers=ADMIN).json()
    assert admin[0]["recipients"] == RECIPIENTS


def test_email_log_limit_and_unknown_company(api: Api) -> None:
    seeded(api)
    assert api.get("/api/companies/kemira/emails").json() == []
    assert api.get("/api/companies/kemira/emails?limit=0").status_code == 422
    assert api.get("/api/companies/nope/emails").status_code == 404
