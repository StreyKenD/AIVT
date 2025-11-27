"""Utilities for broadcasting orchestrator events and telemetry.

This module contains the :class:`EventDispatcher`, a thin abstraction over the
event broker that centralises how we fan out orchestrator events (WebSocket,
telemetry, etc.) and emit pipeline metrics.  Keeping the publishing helpers in a
single place keeps the high-level orchestration logic focused on state
transitions while this module takes care of formatting the outbound payloads.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .broker import EventBroker


class EventDispatcher:
    """Publish orchestrator events and derived telemetry."""

    def __init__(self, broker: EventBroker) -> None:
        self._broker = broker

    async def publish(self, message: Dict[str, Any]) -> None:
        """Send a raw event through the broker."""
        await self._broker.publish(message)

    async def publish_status(self, snapshot: Dict[str, Any]) -> None:
        """Broadcast the current orchestrator snapshot."""
        await self.publish({"type": "status", "payload": snapshot})

    async def publish_pipeline_metric(
        self,
        stage: str,
        latency_ms: float,
        request_id: Optional[str],
        mode: str,
    ) -> None:
        """Emit latency metrics for the voice pipeline."""
        payload: Dict[str, Any] = {
            "stage": stage,
            "latency_ms": round(latency_ms, 2),
            "mode": mode,
        }
        if request_id:
            payload["request_id"] = request_id
        await self.publish({"type": "pipeline.metric", "payload": payload})


__all__ = ["EventDispatcher"]
