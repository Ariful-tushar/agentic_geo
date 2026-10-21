"""Per-provider concurrency, retries with backoff, and daily-stop detection (SPEC 7.3).

A 429 is a daily stop only when the daily quota is used up (Groq: `x-ratelimit-remaining-requests`
is 0, or the error names a per-day limit such as TPD/RPD/PerDay) or when the wait is longer than
`*_DAILY_STOP_SECONDS` (default 900). Shorter waits are slept and the run goes on.
"""

import asyncio
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from app.config import get_settings

DEFAULT_DAILY_STOP_SECONDS = 900
_DAILY_LIMIT_TEXT = re.compile(r"(?:tpd|rpd)|per[ _-]?day", re.IGNORECASE)
RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4
_BASE_DELAY = 2.0

Sleep = Callable[[float], Awaitable[None]]


class DailyStop(Exception):
    """The provider is out of quota for a long time; stop using it for this run."""

    def __init__(self, provider: str, wait_seconds: float | None = None) -> None:
        self.provider = provider
        self.wait_seconds = wait_seconds
        super().__init__(f"{provider} is exhausted (retry in {wait_seconds}s)")


_exhausted: set[str] = set()
_semaphores: dict[tuple[str, int], asyncio.Semaphore] = {}
_token_log: dict[str, deque[tuple[float, int]]] = {}


def reset_limits() -> None:
    _exhausted.clear()
    _semaphores.clear()
    _token_log.clear()


def is_exhausted(provider: str) -> bool:
    return provider in _exhausted


def _concurrency(provider: str) -> int:
    settings = get_settings()
    return {
        "groq": settings.groq_max_concurrency,
        "gemini": settings.gemini_max_concurrency,
    }.get(provider, 1)


def _semaphore(provider: str) -> asyncio.Semaphore:
    key = (provider, id(asyncio.get_running_loop()))
    if key not in _semaphores:
        _semaphores[key] = asyncio.Semaphore(_concurrency(provider))
    return _semaphores[key]


_DURATION = re.compile(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?")


def parse_duration(value: str | None) -> float | None:
    """Seconds from '2', '37s', '2m59.56s' or '1h2m'; None if it is not a duration."""
    if not value:
        return None
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    match = _DURATION.fullmatch(value)
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds = (float(p) if p else 0.0 for p in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def status_of(exc: BaseException) -> int | None:
    """HTTP status from groq/openai errors (`status_code`) or google-genai errors (`code`)."""
    for name in ("status_code", "code"):
        value = getattr(exc, name, None)
        if isinstance(value, int):
            return value
    return None


def daily_stop_seconds(provider: str) -> float:
    """Waits longer than this are treated as "out of quota for today"."""
    settings = get_settings()
    return {
        "groq": settings.groq_daily_stop_seconds,
        "gemini": settings.gemini_daily_stop_seconds,
    }.get(provider, DEFAULT_DAILY_STOP_SECONDS)


def is_daily_limit(exc: BaseException) -> bool:
    """True when the provider says the daily quota is used up, however short its retry-after."""
    response: Any = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        left = str(headers.get("x-ratelimit-remaining-requests", "")).strip()
        if left == "0":  # Groq: the daily request quota (RPD) is used up
            return True
    return bool(_DAILY_LIMIT_TEXT.search(str(exc)))


def retry_after_of(exc: BaseException) -> float | None:
    """Seconds to wait, from `retry-after` / Groq's token reset header or Gemini's retryDelay."""
    response: Any = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        for name in ("retry-after", "x-ratelimit-reset-tokens"):
            seconds = parse_duration(headers.get(name))
            if seconds is not None:
                return seconds
    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        for item in details.get("error", {}).get("details", []):
            if "retryDelay" in item:
                return parse_duration(item["retryDelay"])
    return None


def _is_retryable(exc: BaseException) -> bool:
    status = status_of(exc)
    if status is not None:
        return status in RETRY_STATUSES
    name = type(exc).__name__
    return isinstance(exc, ConnectionError | TimeoutError) or name.endswith(
        ("ConnectionError", "TimeoutError", "Timeout")
    )


async def wait_for_token_budget(provider: str, limit: int, sleep: Sleep = asyncio.sleep) -> None:
    """Groq tokens-per-minute budget: wait until the last 60 seconds have room."""
    log = _token_log.setdefault(provider, deque())
    while True:
        now = time.monotonic()
        while log and now - log[0][0] >= 60:
            log.popleft()
        if sum(tokens for _, tokens in log) < limit:
            return
        await sleep(max(1.0, 60 - (now - log[0][0])))


def record_tokens(provider: str, tokens: int) -> None:
    _token_log.setdefault(provider, deque()).append((time.monotonic(), tokens))


async def call_with_retries[T](
    provider: str, fn: Callable[[], Awaitable[T]], sleep: Sleep = asyncio.sleep
) -> T:
    """Run `fn` under the provider's semaphore; retry 429/5xx; DailyStop when out for the day."""
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        if is_exhausted(provider):
            raise DailyStop(provider)
        try:
            async with _semaphore(provider):
                return await fn()
        except Exception as exc:
            if not _is_retryable(exc):
                raise
            wait = retry_after_of(exc)
            if is_daily_limit(exc) or (wait is not None and wait > daily_stop_seconds(provider)):
                _exhausted.add(provider)
                raise DailyStop(provider, wait) from exc
            if attempt == _MAX_ATTEMPTS:
                raise
            await sleep(wait if wait is not None else _BASE_DELAY * 2 ** (attempt - 1))
    raise AssertionError("unreachable")
