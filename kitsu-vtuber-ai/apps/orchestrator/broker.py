from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from libs.telemetry import TelemetryClient

logger = logging.getLogger(__name__)


class EventBroker:
    """Simple pub/sub broker for broadcasting orchestrator events."""

    def __init__(self, telemetry: Optional[TelemetryClient] = None) -> None:
        self._subscribers: Dict[int, asyncio.Queue[Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._counter = 0
        self._telemetry = telemetry

    async def subscribe(self) -> tuple[int, asyncio.Queue[Dict[str, Any]]]:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        async with self._lock:
            token = self._counter
            self._counter += 1
            self._subscribers[token] = queue
        return token, queue

    async def unsubscribe(self, token: int) -> None:
        async with self._lock:
            self._subscribers.pop(token, None)

    async def publish(self, message: Dict[str, Any]) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.values())
        for queue in subscribers:
            await queue.put(message)

        telemetry = self._telemetry
        if telemetry is None:
            return
        try:
            await telemetry.publish_event(message)
        except Exception:
            logger.debug(
                "Telemetry publish failed for %s",
                message.get("type", "unknown"),
                exc_info=True,
            )


__all__ = ["EventBroker"]
