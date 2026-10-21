import pytest

from app.llm import limits
from app.llm.limits import DailyStop, call_with_retries, is_exhausted, parse_duration
from tests.fakes import FakeHTTPError


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2", 2.0), ("37s", 37.0), ("2m59.56s", 179.56), ("1h2m", 3720.0)],
)
def test_parse_duration(value: str, expected: float) -> None:
    assert parse_duration(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", ["", None, "abc"])
def test_parse_duration_rejects_non_durations(value: str | None) -> None:
    assert parse_duration(value) is None


class Flaky:
    def __init__(self, errors: list[Exception]) -> None:
        self.errors = errors
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


async def no_sleep(_: float) -> None:
    return None


async def test_retries_429_with_short_wait_then_succeeds() -> None:
    fn = Flaky([FakeHTTPError(429, {"retry-after": "2"}), FakeHTTPError(503)])
    assert await call_with_retries("groq", fn, no_sleep) == "ok"
    assert fn.calls == 3


async def test_gives_up_after_max_attempts() -> None:
    fn = Flaky([FakeHTTPError(500) for _ in range(10)])
    with pytest.raises(FakeHTTPError):
        await call_with_retries("groq", fn, no_sleep)
    assert fn.calls == 4


async def test_client_errors_are_not_retried() -> None:
    fn = Flaky([FakeHTTPError(400)])
    with pytest.raises(FakeHTTPError):
        await call_with_retries("groq", fn, no_sleep)
    assert fn.calls == 1


async def test_long_wait_is_a_daily_stop_and_blocks_the_provider() -> None:
    fn = Flaky([FakeHTTPError(429, {"retry-after": "3600"})])
    with pytest.raises(DailyStop):
        await call_with_retries("groq", fn, no_sleep)
    assert is_exhausted("groq")
    again = Flaky([])
    with pytest.raises(DailyStop):
        await call_with_retries("groq", again, no_sleep)
    assert again.calls == 0
    assert not is_exhausted("gemini")


async def test_token_budget_waits_when_full() -> None:
    limits.record_tokens("groq", 9000)
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)
        limits._token_log["groq"].clear()

    await limits.wait_for_token_budget("groq", 8000, fake_sleep)
    assert len(waits) == 1
