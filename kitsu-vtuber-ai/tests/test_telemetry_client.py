from __future__ import annotations

import json
import logging
from typing import Any, Dict

import httpx
import pytest

from libs.telemetry import TelemetryClient


@pytest.mark.asyncio()
async def test_telemetry_client_uses_expected_headers_and_source() -> None:
    captured: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        captured["json"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        base_url="https://telemetry.local", transport=transport
    ) as async_client:
        client = TelemetryClient(
            "https://telemetry.local",
            api_key="secret",
            source="tts_worker",
            client=async_client,
        )
        await client.publish("tts.completed", {"status": "ok"})
        await client.aclose()

    headers = captured["headers"]
    assert headers.get("x-api-key") == "secret"
    assert "authorization" not in headers

    payload = captured["json"]
    assert payload["type"] == "tts.completed"
    assert payload["payload"] == {"status": "ok"}
    assert payload["source"] == "tts_worker"


@pytest.mark.asyncio()
async def test_publish_event_propagates_api_key_and_source() -> None:
    captured: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        captured["json"] = json.loads(request.content.decode())
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        base_url="https://telemetry.local", transport=transport
    ) as async_client:
        client = TelemetryClient(
            "https://telemetry.local",
            api_key="publisher-key",
            source="orchestrator",
            client=async_client,
        )
        await client.publish_event({"type": "status", "payload": {"state": "ok"}})
        await client.aclose()

    headers = captured["headers"]
    assert headers.get("x-api-key") == "publisher-key"
    assert "authorization" not in headers

    body = captured["json"]
    assert body["type"] == "status"
    assert body["payload"] == {"state": "ok"}
    assert body["source"] == "orchestrator"
    assert isinstance(body["ts"], (int, float))


@pytest.mark.asyncio()
async def test_publish_event_maps_service_alias(caplog: pytest.LogCaptureFixture) -> None:
    captured: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content.decode())
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(
        base_url="https://telemetry.local", transport=transport
    ) as async_client:
        client = TelemetryClient(
            "https://telemetry.local",
            api_key=None,
            source=None,
            client=async_client,
        )
        caplog.set_level(logging.WARNING)
        await client.publish_event(
            {"type": "legacy", "service": "legacy_service", "payload": {"ok": True}}
        )
        await client.aclose()

    payload = captured["json"]
    assert payload["source"] == "legacy_service"
    assert payload["payload"] == {"ok": True}
    assert "legacy 'service' field" in caplog.text
