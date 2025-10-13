from __future__ import annotations

import asyncio
import importlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Garante que o pacote "api" possa ser importado via caminho relativo.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("TELEMETRY_API_KEY", "test-key")

from api import main, storage  # noqa: E402


API_HEADERS = {"x-api-key": os.environ["TELEMETRY_API_KEY"]}


@pytest.fixture()
def telemetry_db(tmp_path, monkeypatch):
    db_path = tmp_path / "telemetry.db"
    monkeypatch.setenv("TELEMETRY_DB_PATH", str(db_path))
    return db_path


def test_health_endpoint(telemetry_db):
    async def _scenario() -> None:
        await storage.init_db(db_path=str(telemetry_db))
        transport = ASGITransport(app=main.app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver", headers=API_HEADERS
        ) as async_client:
            response = await async_client.get("/health")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}

    asyncio.run(_scenario())


def test_event_ingest_batch_filter_and_export(telemetry_db):
    async def _scenario() -> None:
        await storage.init_db(db_path=str(telemetry_db))
        transport = ASGITransport(app=main.app)
        async with AsyncClient(
            transport=transport, base_url="http://testserver", headers=API_HEADERS
        ) as async_client:
            now = datetime.now(timezone.utc).replace(microsecond=0)
            single_event = {
                "type": "emotion",
                "ts": now.isoformat(),
                "payload": {"mood": "happy", "intensity": 0.8},
            }

            single_response = await async_client.post("/events", json=single_event)
            assert single_response.status_code == 200
            assert "id" in single_response.json()

            batch_payload = [
                {
                    "type": "emotion",
                    "ts": (now + timedelta(seconds=1)).isoformat(),
                    "payload": {"mood": "excited"},
                },
                {
                    "type": "status",
                    "ts": (now + timedelta(seconds=2)).isoformat(),
                    "payload": {"state": "ok"},
                },
            ]

            batch_response = await async_client.post("/events", json=batch_payload)
            assert batch_response.status_code == 200
            body = batch_response.json()
            assert "ids" in body and len(body["ids"]) == 2

            gpu_event = {
                "type": "hardware.gpu",
                "ts": (now + timedelta(seconds=3)).isoformat(),
                "payload": {
                    "index": 0,
                    "name": "Mock GPU",
                    "temperature_c": 62.0,
                    "utilization_pct": 70.0,
                    "memory_used_mb": 4096.0,
                    "memory_total_mb": 8192.0,
                    "memory_pct": 50.0,
                    "fan_speed_pct": 40.0,
                    "power_w": 150.0,
                },
            }
            gpu_response = await async_client.post("/events", json=gpu_event)
            assert gpu_response.status_code == 200

            events_response = await async_client.get(
                "/events", params={"type": "emotion", "limit": 5}
            )
            assert events_response.status_code == 200
            emotion_items = events_response.json()
            assert emotion_items
            assert all(item["type"] == "emotion" for item in emotion_items)
            assert all("ts" in item and "payload" in item for item in emotion_items)

            legacy_filter = await async_client.get(
                "/events", params={"event_type": "status"}
            )
            assert legacy_filter.status_code == 200
            legacy_items = legacy_filter.json()
            assert legacy_items
            assert all(item["type"] == "status" for item in legacy_items)

            export_response = await async_client.get("/events/export")
            assert export_response.status_code == 200
            csv_content = (await export_response.aread()).decode("utf-8")
            lines = [line for line in csv_content.splitlines() if line]
            assert lines[0] == "ts,type,json_payload"
            assert "emotion" in csv_content
            assert "json_payload" in csv_content

            metrics_response = await async_client.get("/metrics/latest")
            assert metrics_response.status_code == 200
            metrics_body = metrics_response.json()
            assert "metrics" in metrics_body and metrics_body["metrics"]
            gpu_metrics = metrics_body["metrics"].get("hardware.gpu")
            assert gpu_metrics is not None
            assert gpu_metrics["temperature_c"]["avg"] == 62.0
            assert gpu_metrics["utilization_pct"]["avg"] == 70.0
            assert gpu_metrics["memory_pct"]["avg"] == 50.0

            prune_response = await async_client.post(
                "/maintenance/prune", params={"max_age_seconds": 60}
            )
            assert prune_response.status_code == 200
            assert "removed" in prune_response.json()

    asyncio.run(_scenario())


def test_uvicorn_import(telemetry_db, monkeypatch):
    monkeypatch.setenv("TELEMETRY_DB_PATH", str(telemetry_db))
    module = importlib.import_module("api.main")
    assert hasattr(module, "app")


def test_storage_export_helper(telemetry_db):
    async def _scenario() -> None:
        await storage.init_db(db_path=str(telemetry_db))
        await storage.insert_event(
            storage.TelemetryEvent(
                type="ping",
                ts=datetime.now(timezone.utc).isoformat(),
                payload={"ok": True},
                source="bot",
            ),
            db_path=str(telemetry_db),
        )
        csv_content = await storage.export_events(db_path=str(telemetry_db))
        assert "ts,type,json_payload" in csv_content
        assert "ping" in csv_content
        assert '"ok"' in csv_content and "true" in csv_content

    asyncio.run(_scenario())


def test_requires_api_key(telemetry_db):
    async def _scenario() -> None:
        await storage.init_db(db_path=str(telemetry_db))
        transport = ASGITransport(app=main.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as insecure_client:
            response = await insecure_client.get("/events")
        assert response.status_code == 401

    asyncio.run(_scenario())
