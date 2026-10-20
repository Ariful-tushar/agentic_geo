from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.profiles.loader import ProfileError, load_profile_file, parse_profile
from app.schemas.profile import ProfileIn

KEMIRA = Path(__file__).parents[2] / "seed" / "kemira.profile.yaml"


def valid() -> dict[str, Any]:
    return {
        "id": "acme",
        "name": "Acme",
        "contact_emails": ["boss@example.com"],
        "competitors": [{"name": "Rival"}],
        "knowledge_sources": ["https://acme.com/about"],
        "fact_questions": [{"code": "Q01", "text": "Where?", "expected_answer": "Oslo."}],
        "generic_questions": [{"code": "G01", "text": "Who sells anvils?"}],
    }


def fact(**extra: Any) -> dict[str, Any]:
    return {"code": "Q01", "text": "x", "expected_answer": "y", **extra}


def error_for(data: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as info:
        ProfileIn.model_validate(data)
    return str(info.value)


def test_valid_profile_passes() -> None:
    assert ProfileIn.model_validate(valid()).id == "acme"


def test_seed_profile_is_valid() -> None:
    profile = load_profile_file(KEMIRA)
    assert len(profile.fact_questions) == 18
    assert len(profile.generic_questions) == 6


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"id": "Not A Slug"}, "slug"),
        ({"fact_questions": []}, "at least 1"),
        ({"competitors": []}, "at least 1"),
        ({"contact_emails": ["not-an-email"]}, "email"),
        ({"knowledge_sources": ["not a url"]}, "url"),
        ({"surprise": 1}, "Extra inputs"),
        ({"fact_questions": [fact(expected_answer="")]}, "expected_answer"),
        ({"fact_questions": [{"code": "Q01", "text": "x"}]}, "expected_answer"),
        ({"fact_questions": [fact(tolerance=1)]}, "only allowed together with expected_value"),
        ({"fact_questions": [fact(unit="people")]}, "only allowed together with expected_value"),
        ({"fact_questions": [fact(), fact(text="z")]}, "duplicate question code"),
        ({"generic_questions": [{"code": "Q01", "text": "clash"}]}, "duplicate question code"),
        ({"competitors": [{"name": "Rival"}, {"name": "rival"}]}, "duplicate competitor"),
    ],
)
def test_invalid_profiles_give_clear_errors(change: dict[str, Any], expected: str) -> None:
    assert expected.lower() in error_for({**valid(), **change}).lower()


def test_numeric_question_with_zero_tolerance_is_valid() -> None:
    data = {**valid(), "fact_questions": [fact(expected_value=4900, tolerance=0, unit="people")]}
    assert ProfileIn.model_validate(data).fact_questions[0].tolerance == 0


def test_parse_profile_reports_readable_errors() -> None:
    with pytest.raises(ProfileError, match=r"validation error"):
        parse_profile("id: acme\nname: Acme\n")
    with pytest.raises(ProfileError, match="mapping"):
        parse_profile("- just\n- a list\n")
    with pytest.raises(ProfileError, match="Invalid YAML"):
        parse_profile("id: [unclosed")
