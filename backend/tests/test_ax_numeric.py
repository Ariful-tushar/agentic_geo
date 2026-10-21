import pytest

from app.agents.ax import numeric
from app.agents.ax.judge import JudgeInput, Verdict, apply_numeric

REVENUE = {"expected_value": 2.8, "tolerance": 0.05, "unit": "EUR billion"}
EMPLOYEES = {"expected_value": 4900.0, "tolerance": 100.0, "unit": "people"}
PERCENT = {"expected_value": 19.1, "tolerance": 0.1, "unit": "percent"}
YEAR = {"expected_value": 2045.0, "tolerance": 0.0, "unit": "year"}
COUNTRIES = {"expected_value": 100.0, "tolerance": 0.0, "unit": "countries (over)"}
WATER = {"expected_value": 21.0, "tolerance": 0.5, "unit": "billion m3"}


def values(text: str, unit: str | None = None) -> list[float]:
    target = numeric.unit_scale(unit)
    return [r for n in numeric.extract_numbers(text) for r in numeric.candidates(n, target)]


# ---- extraction and unit normalisation -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "unit", "expected"),
    [
        ("EUR 2.8 billion", "EUR billion", 2.8),
        ("EUR 2,800 million", "EUR billion", 2.8),
        ("EUR 2.8bn", "EUR billion", 2.8),
        ("EUR 2 800 000 000", "EUR billion", 2.8),
        ("2,8 billion euros", "EUR billion", 2.8),
        ("19.1%", "percent", 19.1),
        ("19.1 percent", "percent", 19.1),
        ("19.1 per cent", "percent", 19.1),
        ("4.9 thousand people", "people", 4900),
        ("4,900 people", "people", 4900),
        ("4 900 people", "people", 4900),
        ("about 5,000 employees", "people", 5000),
        ("the year 2045", "year", 2045),
        ("21 billion cubic metres", "billion m3", 21),
        ("21,000 million m3", "billion m3", 21),
    ],
)
def test_numbers_are_normalised_to_the_unit(text: str, unit: str, expected: float) -> None:
    assert any(abs(v - expected) < 1e-6 for v in values(text, unit))


def test_all_numbers_in_a_sentence_are_found() -> None:
    found = [n.value for n in numeric.extract_numbers("Founded in 1920, it has 4,900 staff.")]
    assert found == [1920.0, 4900.0]


def test_a_unit_symbol_must_touch_the_number() -> None:
    number = numeric.extract_numbers("a volume of 21 m3 per day")[0]
    assert (number.value, number.multiplier) == (21.0, None)  # "m3" is cubic metres, not millions


def test_sentence_around_returns_an_exact_substring() -> None:
    text = "Intro line.\nIn 2025 revenue was EUR 2.8 billion. Next sentence."
    number = numeric.extract_numbers(text)[1]
    sentence = numeric.sentence_around(text, number.start, number.end)
    assert sentence == "In 2025 revenue was EUR 2.8 billion."
    assert sentence in text


# ---- tolerance verdict ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("diff", "tolerance", "verdict"),
    [
        (0, 100, "correct"),
        (100, 100, "correct"),  # exactly the tolerance still counts as within it
        (101, 100, "partial"),
        (200, 100, "partial"),
        (201, 100, "wrong"),
        (0, 0, "correct"),
        (0.001, 0, "wrong"),  # tolerance 0 means exact match only: never partial
    ],
)
def test_verdict_for(diff: float, tolerance: float, verdict: str) -> None:
    assert numeric.verdict_for(diff, tolerance) == verdict


def test_assess_returns_none_without_numbers() -> None:
    assert numeric.assess("Kemira is based in Helsinki.", 4900, 100, "people") is None


# ---- applying it on top of the judge -------------------------------------------------------


def run_numeric(
    spec: dict, answer: str, quote: str | None, verdict: str = "correct", verified: bool = True
) -> Verdict:
    item = JudgeInput("Q", "question?", "expected", answer, **spec)
    judged = Verdict(verdict, "judge reason", quote, verified and quote is not None, "judge")
    return apply_numeric(item, judged)


@pytest.mark.parametrize(
    ("spec", "answer", "expected"),
    [
        (REVENUE, "Revenue was EUR 2.8 billion.", "correct"),
        (REVENUE, "Revenue was EUR 2,800 million.", "correct"),
        (REVENUE, "Revenue was about EUR 2.83 billion.", "correct"),
        (REVENUE, "Revenue was EUR 2.9 billion.", "partial"),
        (REVENUE, "Revenue was EUR 3.4 billion.", "wrong"),
        (EMPLOYEES, "It employs approximately 4,900 people.", "correct"),
        (EMPLOYEES, "It employs 4.9 thousand people.", "correct"),
        (EMPLOYEES, "It employs about 5,000 people.", "correct"),
        (EMPLOYEES, "It employs about 5,100 people.", "partial"),
        (EMPLOYEES, "It employs about 5,300 people.", "wrong"),
        (PERCENT, "Share was 19.1%.", "correct"),
        (PERCENT, "Share was 19.2 percent.", "correct"),
        (PERCENT, "Share was 19.3 percent.", "partial"),
        (PERCENT, "Share was 25 percent.", "wrong"),
        (YEAR, "Net zero by 2045.", "correct"),
        (YEAR, "Net zero by 2046.", "wrong"),
        (YEAR, "Net zero by 2050.", "wrong"),
        (COUNTRIES, "Active in over 100 countries.", "correct"),
        (COUNTRIES, "Active in more than 110 countries.", "wrong"),
        (WATER, "Treats 21 billion cubic metres.", "correct"),
    ],
)
def test_numeric_override_decides_by_tolerance(spec: dict, answer: str, expected: str) -> None:
    result = run_numeric(spec, answer, quote=answer, verdict="wrong")
    assert result.verdict == expected
    assert result.method == "numeric"
    assert result.quote_verified


def test_numeric_overrides_a_wrong_judge_in_both_directions() -> None:
    right = run_numeric(EMPLOYEES, "About 4,900 people.", "About 4,900 people.", "wrong")
    wrong = run_numeric(EMPLOYEES, "About 9,000 people.", "About 9,000 people.", "correct")
    assert (right.verdict, wrong.verdict) == ("correct", "wrong")


def test_numbers_come_from_the_judges_quote_first() -> None:
    answer = "Founded in 1920. Today Kemira employs 4,900 people. It has 40 plants."
    quote = "Today Kemira employs 4,900 people."
    result = run_numeric(EMPLOYEES, answer, quote, "wrong")
    assert result.verdict == "correct"
    assert result.quote == quote  # the judge's quote is kept


def test_quote_number_is_not_mixed_with_other_numbers_of_the_answer() -> None:
    # the quote says 9,000 (wrong); 4,900 elsewhere in the answer must not rescue it
    answer = "Today Kemira employs 9,000 people. Last year it had 4,900 people."
    result = run_numeric(EMPLOYEES, answer, "Today Kemira employs 9,000 people.", "correct")
    assert result.verdict == "wrong"


def test_whole_answer_is_used_only_when_the_quote_has_no_number() -> None:
    answer = "Kemira is a Finnish company. It employs 4,900 people."
    result = run_numeric(EMPLOYEES, answer, "Kemira is a Finnish company.", "partial")
    assert result.verdict == "correct"
    assert result.quote == "It employs 4,900 people."  # sentence with the number, taken from answer
    assert result.quote_verified


def test_unverified_quote_is_ignored_for_numbers() -> None:
    answer = "It employs 4,900 people."
    result = run_numeric(EMPLOYEES, answer, "It employs 9,000 people.", "wrong", verified=False)
    assert result.verdict == "correct"


def test_no_answer_stays_no_answer_even_with_an_unrelated_number() -> None:
    answer = "I do not know. Kemira was founded in 1920."
    result = run_numeric(EMPLOYEES, answer, None, "no_answer")
    assert result.verdict == "no_answer"
    assert result.method == "judge"


def test_no_number_at_all_keeps_the_judges_verdict() -> None:
    result = run_numeric(EMPLOYEES, "Several thousand staff.", "Several thousand staff.", "partial")
    assert result.verdict == "partial"
    assert result.method == "judge"


def test_questions_without_expected_value_are_never_overridden() -> None:
    item = JudgeInput("Q", "q?", "Helsinki", "Helsinki, 4,900 people")
    judged = Verdict("correct", "ok", "Helsinki", True, "judge")
    assert apply_numeric(item, judged) is judged


def test_reason_is_short_and_mentions_expected_and_found() -> None:
    result = run_numeric(EMPLOYEES, "About 5,100 people.", "About 5,100 people.", "correct")
    assert "4,900" in result.reason and "5,100" in result.reason
    assert len(result.reason.split()) <= 25
