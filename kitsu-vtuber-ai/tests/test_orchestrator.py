from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def load_orchestrator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, restore: bool = False):
    monkeypatch.setenv("MEMORY_DB_PATH", str(tmp_path / "memory.sqlite3"))
    monkeypatch.setenv("RESTORE_CONTEXT", "true" if restore else "false")
    module = importlib.import_module("apps.orchestrator.main")
    return importlib.reload(module)


def test_status_and_persona_update(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)
    with TestClient(module.app) as client:
        response = client.get("/status")
        assert response.status_code == 200
        data = response.json()
        assert data["persona"]["style"] == "kawaii"

        update = client.post("/persona", json={"style": "chaotic", "chaos_level": 0.8})
        assert update.status_code == 200

        refreshed = client.get("/status")
        assert refreshed.status_code == 200
        persona = refreshed.json()["persona"]
        assert persona["style"] == "chaotic"
        assert persona["chaos_level"] == 0.8
        assert refreshed.json()["memory"]["restore_enabled"] is False


def test_toggle_and_ingest_chat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)
    with TestClient(module.app) as client:
        result = client.post("/toggle/tts_worker", json={"enabled": False})
        assert result.status_code == 200
        payload = result.json()
        assert payload["module"] == "tts_worker"
        assert payload["enabled"] is False

        ingest = client.post("/ingest/chat", json={"role": "user", "text": "Hello there!"})
        assert ingest.status_code == 200
        assert ingest.json()["status"] == "accepted"

        refreshed = client.get("/status").json()
        assert refreshed["modules"]["tts_worker"]["state"] == "offline"


def test_restore_context_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)
    with TestClient(module.app) as client:
        for _ in range(6):
            client.post("/ingest/chat", json={"role": "user", "text": "Ping!"})

    module_restored = load_orchestrator(monkeypatch, tmp_path, restore=True)
    with TestClient(module_restored.app) as client:
        status = client.get("/status").json()
        assert status["restore_context"] is True
        assert status["memory"]["current_summary"] is not None
