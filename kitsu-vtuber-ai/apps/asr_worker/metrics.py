from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from libs.telemetry import TelemetryClient


class ASRTelemetry:
    """Thin wrapper around TelemetryClient with ASR-specific helpers."""

    def __init__(self, client: Optional[TelemetryClient]) -> None:
        self._client = client
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()

    async def cycle_started(self, attempt: int, backoff_seconds: float) -> None:
        await self._publish(
            "asr.worker.cycle_started",
            {
                "attempt": attempt,
                "backoff_seconds": backoff_seconds,
            },
        )

    async def cycle_completed(
        self,
        attempt: int,
        outcome: str,
        *,
        detail: Optional[str] = None,
    ) -> None:
        payload: Dict[str, Any] = {
            "attempt": attempt,
            "outcome": outcome,
        }
        if detail:
            payload["detail"] = detail
        await self._publish("asr.worker.cycle_completed", payload)

    async def segment_partial(
        self,
        *,
        segment: int,
        latency_ms: float,
        text: str,
        confidence: Optional[float],
        language: Optional[str],
    ) -> None:
        await self._publish(
            "asr.segment.partial",
            {
                "segment": segment,
                "latency_ms": latency_ms,
                "text_length": len(text),
                "confidence": confidence,
                "language": language,
            },
        )

    async def segment_final(
        self,
        *,
        segment: int,
        duration_ms: float,
        confidence: Optional[float],
        language: Optional[str],
        text: str,
    ) -> None:
        await self._publish(
            "asr.segment.final",
            {
                "segment": segment,
                "duration_ms": duration_ms,
                "text_length": len(text),
                "confidence": confidence,
                "language": language,
            },
        )

    async def segment_skipped(
        self,
        *,
        segment: int,
        reason: str,
        language: Optional[str],
        text_length: int,
    ) -> None:
        await self._publish(
            "asr.segment.skipped",
            {
                "segment": segment,
                "reason": reason,
                "language": language,
                "text_length": text_length,
            },
        )

    async def _publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._client is None:
            return
        async with self._lock:
            await self._client.publish(event_type, payload)


def create_telemetry() -> ASRTelemetry:
    client = TelemetryClient.from_env(service="asr_worker")
    return ASRTelemetry(client)


__all__ = ["ASRTelemetry", "create_telemetry"]
