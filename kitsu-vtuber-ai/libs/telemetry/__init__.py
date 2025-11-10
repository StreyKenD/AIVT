from __future__ import annotations

import asyncio
import logging
import os
import time
import warnings
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("kitsu.telemetry")


def _normalize_source(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class TelemetryClient:
    """Async publisher for the telemetry API used by workers/services."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: Optional[str] = None,
        source: Optional[str] = None,
        service: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._source = _normalize_source(source) or _normalize_source(service)
        self._client = client
        self._lock = asyncio.Lock()
        self._legacy_service_field_logged = False
        self._missing_source_logged = False
        if service and not source:
            warnings.warn(
                "TelemetryClient 'service' parameter is deprecated; use 'source' instead",
                DeprecationWarning,
                stacklevel=2,
            )

    @classmethod
    def from_env(cls, source: Optional[str] = None) -> Optional["TelemetryClient"]:
        base_url = os.getenv("TELEMETRY_API_URL")
        if not base_url:
            return None
        api_key = os.getenv("TELEMETRY_API_KEY")
        return cls(base_url, api_key=api_key, source=source)

    async def publish(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        ts: Optional[float] = None,
        source: Optional[str] = None,
    ) -> None:
        client = await self._ensure_client()
        headers: Dict[str, str] = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        timestamp = ts if isinstance(ts, (int, float)) else time.time()
        data = {
            "type": event_type,
            "ts": timestamp,
            "payload": payload,
        }
        final_source = _normalize_source(source) or self._source
        if final_source:
            data["source"] = final_source
        else:
            if not self._missing_source_logged:
                logger.warning(
                    "Telemetry event missing source; defaulting to 'unknown'. Please configure a source name."
                )
                self._missing_source_logged = True
            data["source"] = "unknown"
        request_kwargs: Dict[str, Any] = {"json": data}
        if headers:
            request_kwargs["headers"] = headers
        try:
            response = await client.post("/events", **request_kwargs)
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - network noise
            logger.debug(
                "Failed to send telemetry %s: %s", event_type, exc, exc_info=True
            )
            raise

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

    async def publish_event(self, event: Dict[str, Any]) -> None:
        if not isinstance(event, dict):
            raise TypeError("event must be a mapping")
        event_type = str(event.get("type") or "unknown")
        raw_payload = event.get("payload")
        if isinstance(raw_payload, dict):
            payload = dict(raw_payload)
        else:
            payload = {
                key: value
                for key, value in event.items()
                if key not in {"type", "source", "service", "ts"}
            }
        ts_candidate = event.get("ts")
        ts_value: Optional[float]
        if isinstance(ts_candidate, (int, float)):
            ts_value = float(ts_candidate)
        else:
            ts_value = None
        source_candidate = event.get("source")
        legacy_service = event.get("service")
        if legacy_service and not _normalize_source(source_candidate):
            source_candidate = legacy_service
            if not self._legacy_service_field_logged:
                logger.warning(
                    "Telemetry event used legacy 'service' field; mapping to 'source'."
                )
                self._legacy_service_field_logged = True
        source_value = _normalize_source(source_candidate)
        await self.publish(event_type, payload, ts=ts_value, source=source_value)


__all__ = ["TelemetryClient"]
