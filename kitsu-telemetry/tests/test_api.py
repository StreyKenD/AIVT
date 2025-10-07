from __future__ import annotations

import sys
from pathlib import Path

import pytest
import uvicorn
from httpx import AsyncClient

# Garante que o pacote "api" possa ser importado via caminho relativo.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import main, storage  # noqa: E402


@pytest.fixture()
def telemetry_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'telemetry.db'
    monkeypatch.setenv('TELEMETRY_DB_PATH', str(db_path))
    return db_path


@pytest.fixture()
async def client(telemetry_db):
    async with AsyncClient(app=main.app, base_url='http://testserver') as async_client:
        yield async_client


@pytest.mark.asyncio
async def test_health_endpoint(client):
    response = await client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


@pytest.mark.asyncio
async def test_event_flow_and_export(client, telemetry_db):
    payload = {
        'source': 'ui',
        'event_type': 'emotion',
        'payload': {'mood': 'happy', 'intensity': 0.8}
    }

    response = await client.post('/events', json=payload)
    assert response.status_code == 200
    event_id = response.json()['id']
    assert event_id > 0

    events_response = await client.get('/events', params={'limit': 5})
    assert events_response.status_code == 200
    items = events_response.json()
    assert any(item['payload']['mood'] == 'happy' for item in items)

    export_response = await client.get('/events/export')
    assert export_response.status_code == 200
    content = await export_response.aread()
    text = content.decode('utf-8')
    assert 'event_type' in text
    assert 'emotion' in text


def test_uvicorn_import(telemetry_db, monkeypatch):
    monkeypatch.setenv('TELEMETRY_DB_PATH', str(telemetry_db))
    config = uvicorn.Config('api.main:app', port=0, loop='asyncio')
    app = config.load()
    assert callable(app)


@pytest.mark.asyncio
async def test_storage_export_helper(telemetry_db):
    await storage.init_db(db_path=str(telemetry_db))
    await storage.insert_event(
        storage.TelemetryEvent(source='bot', event_type='ping', payload={'ok': True}),
        db_path=str(telemetry_db)
    )
    csv_content = await storage.export_events(db_path=str(telemetry_db))
    assert 'source' in csv_content
    assert 'bot' in csv_content
