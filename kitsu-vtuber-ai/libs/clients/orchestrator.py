from __future__ import annotations

import logging
from typing import Protocol

import httpx

from libs.contracts import ASREventPayload

logger = logging.getLogger("kitsu.clients.orchestrator")


class OrchestratorPublisher(Protocol):
    """Protocol describing the event publishing surface used by the ASR worker."""

    async def publish(self, event: ASREventPayload) -> None: ...


class OrchestratorClient:
    """Publishes ASR events to the orchestrator's broker via HTTP."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    async def publish(self, event: ASREventPayload) -> None:
        try:
            await self._client.post(
                f"{self._base_url}/events/asr",
                json=event.dict(),
            )
        except Exception:  # pragma: no cover - network guard
            logger.warning("Failed to publish %s", event.type, exc_info=True)

    async def aclose(self) -> None:
        await self._client.aclose()


__all__ = ["OrchestratorPublisher", "OrchestratorClient"]
