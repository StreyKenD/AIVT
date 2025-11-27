from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from .utils import load_orchestrator


@pytest.mark.asyncio()
async def test_health_endpoint_reports_modules(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)
    transport = ASGITransport(app=module.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        payload = response.json()
        assert "modules" in payload
        assert "tts_worker" in payload["modules"]
        assert "uptime_seconds" in payload


@pytest.mark.asyncio()
async def test_metrics_endpoint_emits_prometheus_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)
    transport = ASGITransport(app=module.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/metrics")
        assert response.status_code == 200
        body = response.text
        assert "kitsu_request_latency_seconds_count" in body
