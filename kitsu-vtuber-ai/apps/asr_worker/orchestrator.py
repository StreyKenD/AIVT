from __future__ import annotations

from typing import Dict, Protocol

import httpx

from .logger import logger


class OrchestratorPublisher(Protocol):
    async def publish(self, event_type: str, payload: Dict[str, object]) -> None:
        ...


class OrchestratorClient:
    """Publishes ASR events to the orchestrator's broker via HTTP."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    async def publish(self, event_type: str, payload: Dict[str, object]) -> None:
        data = {"type": event_type, **payload}
        try:
            await self._client.post(f"{self._base_url}/events/asr", json=data)
        except Exception as exc:  # pragma: no cover - network guard
            logger.warning("Failed to publish %s: %s", event_type, exc, exc_info=True)

    async def aclose(self) -> None:
        await self._client.aclose()


__all__ = ["OrchestratorPublisher", "OrchestratorClient"]

