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

        if self._telemetry is None:
            return

        event_type = str(message.get("type") or "unknown")
        payload = message.get("payload")
        if not isinstance(payload, dict):
            payload = {
                key: value
                for key, value in message.items()
                if key != "type"
            }
        try:
            await self._telemetry.publish(event_type, payload)
        except Exception:
            logger.debug(
                "Telemetry publish failed for %s", event_type, exc_info=True
            )


__all__ = ["EventBroker"]
