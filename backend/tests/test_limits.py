from types import SimpleNamespace

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


# ---- what counts as a daily stop (D2.3 fix) ------------------------------------------------


class RecordingSleep:
    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


async def test_a_wait_of_259_seconds_is_slept_and_the_run_goes_on() -> None:
    fn, sleep = Flaky([FakeHTTPError(429, {"retry-after": "259.2"})]), RecordingSleep()
    assert await call_with_retries("groq", fn, sleep) == "ok"
    assert sleep.waits == [259.2]
    assert not is_exhausted("groq")


async def test_the_threshold_is_900_seconds_by_default() -> None:
    at_limit = Flaky([FakeHTTPError(429, {"retry-after": "900"})])
    assert await call_with_retries("groq", at_limit, RecordingSleep()) == "ok"
    over = Flaky([FakeHTTPError(429, {"retry-after": "901"})])
    with pytest.raises(DailyStop):
        await call_with_retries("groq", over, RecordingSleep())
    assert is_exhausted("groq")


async def test_the_threshold_is_a_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        limits,
        "get_settings",
        lambda: SimpleNamespace(
            groq_daily_stop_seconds=30,
            gemini_daily_stop_seconds=900,
            groq_max_concurrency=1,
            gemini_max_concurrency=1,
        ),
    )
    with pytest.raises(DailyStop):
        await call_with_retries(
            "groq", Flaky([FakeHTTPError(429, {"retry-after": "31"})]), RecordingSleep()
        )
    assert (
        await call_with_retries(
            "gemini", Flaky([FakeHTTPError(429, {"retry-after": "31"})]), RecordingSleep()
        )
        == "ok"
    )


async def test_daily_request_quota_used_up_is_a_daily_stop_even_with_a_short_wait() -> None:
    headers = {"retry-after": "30", "x-ratelimit-remaining-requests": "0"}
    with pytest.raises(DailyStop):
        await call_with_retries("groq", Flaky([FakeHTTPError(429, headers)]), RecordingSleep())
    assert is_exhausted("groq")


@pytest.mark.parametrize(
    "message",
    [
        "Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 199900",
        "Rate limit reached ... on requests per day (RPD): Limit 1000, Used 1000",
        "429 RESOURCE_EXHAUSTED {'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}",
    ],
)
async def test_an_error_naming_a_daily_limit_is_a_daily_stop(message: str) -> None:
    error = FakeHTTPError(429, {"retry-after": "20"}, message)
    with pytest.raises(DailyStop):
        await call_with_retries("groq", Flaky([error]), RecordingSleep())


async def test_a_per_minute_limit_with_requests_left_is_not_a_daily_stop() -> None:
    headers = {
        "retry-after": "12",
        "x-ratelimit-remaining-requests": "850",
        "x-ratelimit-remaining-tokens": "0",
    }
    message = "Rate limit reached ... on tokens per minute (TPM): Limit 8000, Used 7900"
    fn, sleep = Flaky([FakeHTTPError(429, headers, message)]), RecordingSleep()
    assert await call_with_retries("groq", fn, sleep) == "ok"
    assert sleep.waits == [12.0]


def test_retry_after_prefers_retry_after_then_the_token_reset_not_the_daily_one() -> None:
    both = FakeHTTPError(429, {"retry-after": "7", "x-ratelimit-reset-tokens": "30s"})
    assert limits.retry_after_of(both) == 7.0
    tokens_only = FakeHTTPError(
        429, {"x-ratelimit-reset-tokens": "7.66s", "x-ratelimit-reset-requests": "1m26.4s"}
    )
    assert limits.retry_after_of(tokens_only) == pytest.approx(7.66)
