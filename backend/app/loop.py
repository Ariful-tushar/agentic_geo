"""Event loop helper: psycopg 3 async cannot run on Windows' default ProactorEventLoop."""

import asyncio
import selectors
from collections.abc import Awaitable


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop(selectors.SelectSelector())


def run[T](coro: Awaitable[T]) -> T:
    """asyncio.run that works with psycopg on every platform."""
    with asyncio.Runner(loop_factory=selector_loop_factory) as runner:
        return runner.run(coro)
