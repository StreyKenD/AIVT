from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def test_policy_worker_fallback(monkeypatch) -> None:
    monkeypatch.setenv("POLICY_FORCE_MOCK", "1")
    module = importlib.import_module("apps.policy_worker.main")
    module = importlib.reload(module)
    with TestClient(module.app) as client:
        response = client.post(
            "/respond", json={"text": "Hello chat", "persona_style": "chaotic"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "<speech>" in data["content"]
        assert "<mood>" in data["content"]
        assert "<actions>" in data["content"]
        assert data["source"] == "mock"
