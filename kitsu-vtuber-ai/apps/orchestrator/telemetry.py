from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from libs.compat.tenacity_shim import AsyncRetrying, stop_after_attempt, wait_fixed
from libs.telemetry import TelemetryClient

logger = logging.getLogger("kitsu.orchestrator.telemetry")


class TelemetryDispatcher:
    """Wraps a telemetry client with retryable publishing and lifecycle hooks."""

    def __init__(self, client: Optional[TelemetryClient]) -> None:
        self._client = client
        self._retry_factory: Callable[[], AsyncRetrying] = lambda: AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_fixed(0.1),
            reraise=False,
        )

    async def startup(self) -> None:
        if self._client is None:
            return
        try:
            await self._client._ensure_client()  # pylint: disable=protected-access
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.debug("Telemetry startup failed: %s", exc, exc_info=True)

    async def shutdown(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()

    async def publish_event(self, event: Dict[str, Any]) -> None:
        if self._client is None:
            return
        retrying = self._retry_factory()
        last_exc: Exception | None = None
        async for attempt in retrying:
            try:
                async with attempt:
                    await self._client.publish_event(event)
                return
            except Exception as exc:  # pragma: no cover - retry path
                last_exc = exc
                continue
        if getattr(retrying, "_reraise", False) and last_exc is not None:
            raise last_exc


__all__ = ["TelemetryDispatcher"]
