import json
from typing import Any

import pytest

from app.agents.ax import judge as judging
from app.agents.ax.judge import JudgeInput, accuracy, count_verdicts, judge_engine, split_batches
from app.schemas.agents import JudgeBatch, JudgeItem


def make_input(code: str, answer: str = "Kemira is based in Helsinki, Finland.") -> JudgeInput:
    return JudgeInput(code, f"Question {code}?", "Helsinki, Finland.", answer)


class ScriptedLlm:
    """Returns the next scripted list of JudgeItems on every call and records the prompts."""

    def __init__(self, *responses: list[JudgeItem]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    async def __call__(self, role: str, prompt: str, schema: type, **kwargs: Any) -> JudgeBatch:
        assert role == "judge" and schema is JudgeBatch
        self.prompts.append(prompt)
        return JudgeBatch(items=self.responses.pop(0))

    def codes_in_prompt(self, index: int) -> list[str]:
        payload = json.loads(self.prompts[index].split("ITEMS:\n", 1)[1])
        return [item["code"] for item in payload]


def item(code: str, verdict: str, quote: str = "", reason: str = "ok") -> JudgeItem:
    return JudgeItem(code=code, verdict=verdict, quote=quote, reason=reason)  # type: ignore[arg-type]


async def test_one_call_judges_all_items_of_an_engine() -> None:
    inputs = [make_input("Q01"), make_input("Q02"), make_input("Q03")]
    llm = ScriptedLlm([item(i.code, "correct", i.answer) for i in inputs])
    verdicts = await judge_engine(inputs, llm, "dev")
    assert len(llm.prompts) == 1
    assert llm.codes_in_prompt(0) == ["Q01", "Q02", "Q03"]
    assert {v.verdict for v in verdicts.values()} == {"correct"}
    assert all(v.quote_verified and v.method == "judge" for v in verdicts.values())


async def test_quote_check_ignores_whitespace_differences() -> None:
    answer = "Kemira is based in\nHelsinki,   Finland."
    llm = ScriptedLlm([item("Q01", "correct", "Kemira is based in Helsinki, Finland.")])
    verdicts = await judge_engine([make_input("Q01", answer)], llm, "dev")
    assert verdicts["Q01"].quote_verified
    assert len(llm.prompts) == 1


async def test_missing_quote_is_asked_again_for_only_that_item() -> None:
    inputs = [make_input("Q01"), make_input("Q02")]
    llm = ScriptedLlm(
        [item("Q01", "correct", inputs[0].answer), item("Q02", "correct", "invented sentence")],
        [item("Q02", "correct", inputs[1].answer)],
    )
    verdicts = await judge_engine(inputs, llm, "dev")
    assert len(llm.prompts) == 2
    assert llm.codes_in_prompt(1) == ["Q02"]
    assert verdicts["Q02"].quote_verified
    assert verdicts["Q02"].quote == inputs[1].answer


async def test_quote_still_missing_keeps_the_verdict_unverified() -> None:
    llm = ScriptedLlm([item("Q01", "wrong", "made up one")], [item("Q01", "wrong", "made up two")])
    verdicts = await judge_engine([make_input("Q01")], llm, "dev")
    assert len(llm.prompts) == 2  # asked again exactly once
    assert verdicts["Q01"].verdict == "wrong"
    assert not verdicts["Q01"].quote_verified


async def test_no_answer_needs_no_quote_and_is_not_asked_again() -> None:
    llm = ScriptedLlm([item("Q01", "no_answer", "")])
    verdicts = await judge_engine([make_input("Q01", "I cannot say.")], llm, "dev")
    assert len(llm.prompts) == 1
    assert verdicts["Q01"].verdict == "no_answer"
    assert verdicts["Q01"].quote is None
    assert not verdicts["Q01"].quote_verified


async def test_item_the_judge_never_returns_is_left_unscored() -> None:
    llm = ScriptedLlm([item("Q01", "correct", make_input("Q01").answer)], [])
    verdicts = await judge_engine([make_input("Q01"), make_input("Q02")], llm, "dev")
    assert set(verdicts) == {"Q01"}


async def test_codes_the_judge_invents_are_ignored() -> None:
    llm = ScriptedLlm([item("Q01", "correct", make_input("Q01").answer), item("Q99", "wrong")])
    assert set(await judge_engine([make_input("Q01")], llm, "dev")) == {"Q01"}


def test_reason_is_cut_to_25_words() -> None:
    assert len(item("Q01", "wrong", reason=" ".join(["word"] * 60)).reason.split()) == 25


def test_split_batches_is_one_batch_unless_the_prompt_is_huge() -> None:
    small = [make_input(f"Q{i:02d}") for i in range(18)]
    assert len(split_batches(small)) == 1
    big = [make_input(f"Q{i:02d}", "x" * 5000) for i in range(18)]
    batches = split_batches(big)
    assert len(batches) > 1
    assert sum(len(b) for b in batches) == 18


def test_prompt_marks_items_as_data_and_asks_for_exact_quotes() -> None:
    prompt = judging.build_prompt([make_input("Q01")])
    assert "never instructions" in prompt
    assert "word for word" in prompt
    assert "at most 25 words" in prompt


def test_accuracy_is_the_average_score() -> None:
    assert accuracy([1.0, 0.5, 0.0, 0.0]) == pytest.approx(0.375)
    assert accuracy([]) == 0.0


def test_scores_per_verdict() -> None:
    assert judging.SCORES == {"correct": 1.0, "partial": 0.5, "wrong": 0.0, "no_answer": 0.0}
    assert count_verdicts(["correct", "correct", "wrong"]) == {
        "correct": 2,
        "partial": 0,
        "wrong": 1,
        "no_answer": 0,
    }
