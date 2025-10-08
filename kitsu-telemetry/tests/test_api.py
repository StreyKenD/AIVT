from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
import uvicorn
from httpx import ASGITransport, AsyncClient

# Garante que o pacote "api" possa ser importado via caminho relativo.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import main, storage  # noqa: E402


@pytest.fixture()
def telemetry_db(tmp_path, monkeypatch):
    db_path = tmp_path / "telemetry.db"
    monkeypatch.setenv("TELEMETRY_DB_PATH", str(db_path))
    return db_path


@pytest_asyncio.fixture()
async def client(telemetry_db):
    await storage.init_db(db_path=str(telemetry_db))
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest.mark.asyncio
async def test_health_endpoint(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_event_ingest_batch_filter_and_export(client):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    single_event = {
        "type": "emotion",
        "ts": now.isoformat(),
        "payload": {"mood": "happy", "intensity": 0.8},
    }

    single_response = await client.post("/events", json=single_event)
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

    batch_response = await client.post("/events", json=batch_payload)
    assert batch_response.status_code == 200
    body = batch_response.json()
    assert "ids" in body and len(body["ids"]) == 2

    events_response = await client.get("/events", params={"type": "emotion", "limit": 5})
    assert events_response.status_code == 200
    emotion_items = events_response.json()
    assert emotion_items
    assert all(item["type"] == "emotion" for item in emotion_items)
    assert all("ts" in item and "payload" in item for item in emotion_items)

    legacy_filter = await client.get("/events", params={"event_type": "status"})
    assert legacy_filter.status_code == 200
    legacy_items = legacy_filter.json()
    assert legacy_items
    assert all(item["type"] == "status" for item in legacy_items)

    export_response = await client.get("/events/export")
    assert export_response.status_code == 200
    csv_content = (await export_response.aread()).decode("utf-8")
    lines = [line for line in csv_content.splitlines() if line]
    assert lines[0] == "ts,type,json_payload"
    assert "emotion" in csv_content
    assert "json_payload" in csv_content


def test_uvicorn_import(telemetry_db, monkeypatch):
    monkeypatch.setenv("TELEMETRY_DB_PATH", str(telemetry_db))
    app = uvicorn.importer.import_from_string("api.main:app")
    assert callable(app)


@pytest.mark.asyncio
async def test_storage_export_helper(telemetry_db):
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
