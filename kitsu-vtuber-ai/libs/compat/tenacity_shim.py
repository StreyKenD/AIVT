"""Fallback minimal implementation of ``tenacity`` used in tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator

__all__ = [
    "AsyncRetrying",
    "stop_after_attempt",
    "wait_fixed",
    "wait_exponential",
]


@dataclass
class _StopAfterAttempt:
    attempts: int


def stop_after_attempt(attempts: int) -> _StopAfterAttempt:
    return _StopAfterAttempt(max(1, int(attempts)))


@dataclass
class _WaitStrategy:
    delay: float | None = None


def wait_fixed(seconds: float) -> _WaitStrategy:
    return _WaitStrategy(delay=float(seconds))


def wait_exponential(**_: Any) -> _WaitStrategy:
    return _WaitStrategy()


class _RetryAttempt:
    def __init__(self, parent: "AsyncRetrying") -> None:
        self._parent = parent

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            self._parent._attempt = self._parent._max_attempts
        return False

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc is None:
            self._parent._attempt = self._parent._max_attempts
        return False


class AsyncRetrying:
    """Minimal implementation compatible with our tests."""

    def __init__(
        self,
        *,
        stop: _StopAfterAttempt | None = None,
        wait: _WaitStrategy | None = None,
        reraise: bool | None = None,
        **_: Any,
    ) -> None:
        self._max_attempts = (stop.attempts if stop else 1) or 1
        self._attempt = 0
        self._wait = wait
        self._reraise = bool(reraise)

    def __aiter__(self) -> AsyncIterator[_RetryAttempt]:
        self._attempt = 0
        return self

    async def __anext__(self) -> _RetryAttempt:
        if self._attempt >= self._max_attempts:
            raise StopAsyncIteration
        self._attempt += 1
        return _RetryAttempt(self)
