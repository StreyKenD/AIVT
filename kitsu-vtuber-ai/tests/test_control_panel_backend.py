from __future__ import annotations

from typing import Any, Dict, List

import pytest

pytest.importorskip("fastapi", reason="backend do painel exige FastAPI")
from fastapi.testclient import TestClient

from apps.control_panel_backend import main as control_backend


class StubGateway:
    def __init__(self) -> None:
        self.orchestrator_calls: List[tuple[str, Dict[str, Any]]] = []
        self.telemetry_calls: List[tuple[str, Dict[str, Any]]] = []

    async def orchestrator_get(self, path: str) -> Dict[str, Any]:
        self.orchestrator_calls.append((f"GET {path}", {}))
        return {
            "status": "ok",
            "persona": {"style": "kawaii"},
            "modules": {},
            "control": {"tts_muted": False, "panic_at": None, "active_preset": "default", "panic_reason": None},
        }

    async def orchestrator_post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.orchestrator_calls.append((f"POST {path}", payload))
        if path == "/control/mute":
            return {"type": "control.mute", "muted": payload.get("muted", False)}
        if path == "/control/panic":
            return {"type": "control.panic", "reason": payload.get("reason")}
        return {"type": "control.preset", "preset": payload.get("preset")}

    async def telemetry_get(self, path: str, params: Dict[str, Any] | None = None) -> Any:
        params = params or {}
        self.telemetry_calls.append((path, params))
        if path == "/metrics/latest":
            return {"window_seconds": params.get("window_seconds", 300), "metrics": {}}
        return [
            {"ts": "2025-10-10T10:00:00Z", "type": "soak.result", "payload": {"success": True}}
        ]

    async def telemetry_stream(self, path: str):
        self.telemetry_calls.append((path, {}))
        yield b"ts,type,json_payload\n"
        yield b"2025-10-10T10:00:00Z,control.mute,{\"muted\": true}\n"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    gateway = StubGateway()

    async def _override_gateway() -> StubGateway:
        return gateway

    app = control_backend.app
    app.dependency_overrides[control_backend.get_gateway] = _override_gateway
    test_client = TestClient(app)
    test_client.gateway = gateway  # type: ignore[attr-defined]
    yield test_client
    app.dependency_overrides.clear()


def test_status_and_metrics(client: TestClient) -> None:
    response = client.get("/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"]["status"] == "ok"
    assert payload["metrics"]["window_seconds"] == 300


def test_control_actions_forward_to_orchestrator(client: TestClient) -> None:
    mute = client.post("/control/mute", json={"muted": True})
    assert mute.status_code == 200
    assert mute.json()["muted"] is True

    preset = client.post("/control/preset", json={"preset": "cozy"})
    assert preset.status_code == 200
    assert preset.json()["preset"] == "cozy"

    panic = client.post("/control/panic", json={"reason": "Manual"})
    assert panic.status_code in {200, 202}
    assert panic.json()["type"] == "control.panic"


def test_soak_results_and_export(client: TestClient) -> None:
    soak = client.get("/soak/results", params={"limit": 5})
    assert soak.status_code == 200
    data = soak.json()
    assert len(data["items"]) == 1

    export = client.get("/telemetry/export")
    assert export.status_code == 200
    assert export.text.startswith("ts,type,json_payload")
