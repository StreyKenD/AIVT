from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("kitsu.telemetry")


class TelemetryClient:
    """Async publisher for the telemetry API used by workers/services."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: Optional[str] = None,
        service: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._service = service
        self._client = client
        self._lock = asyncio.Lock()

    @classmethod
    def from_env(cls, service: Optional[str] = None) -> Optional["TelemetryClient"]:
        base_url = os.getenv("TELEMETRY_API_URL")
        if not base_url:
            return None
        api_key = os.getenv("TELEMETRY_API_KEY")
        return cls(base_url, api_key=api_key, service=service)

    async def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        client = await self._ensure_client()
        headers: Dict[str, str] = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        data = {
            "type": event_type,
            "ts": time.time(),
            "payload": payload,
        }
        if self._service:
            data["source"] = self._service
        try:
            response = await client.post("/events", json=data, headers=headers)
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network noise
            logger.debug("Failed to send telemetry %s: %s", event_type, exc)

    async def aclose(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                timeout = httpx.Timeout(3.0, connect=3.0, read=3.0)
                self._client = httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=timeout,
                )
        assert self._client is not None
        return self._client


__all__ = ["TelemetryClient"]
