from __future__ import annotations

import asyncio
import importlib
import textwrap
from pathlib import Path
from typing import Any, Optional

import pytest

from libs.config import reload_app_config

pytest.importorskip("fastapi", reason="orquestrador depende de FastAPI")
from fastapi.testclient import TestClient
try:  # pragma: no cover - prefer real dependency when available
    from tenacity import AsyncRetrying, stop_after_attempt, wait_fixed
except (ImportError, ModuleNotFoundError):  # pragma: no cover - fallback for minimal test envs
    from libs.compat.tenacity_shim import (
        AsyncRetrying,
        stop_after_attempt,
        wait_fixed,
    )


def load_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    restore: bool = False,
    telemetry_url: Optional[str] = None,
    persona_presets_file: Optional[Path] = None,
    persona_default: Optional[str] = None,
):
    monkeypatch.setenv("MEMORY_DB_PATH", str(tmp_path / "memory.sqlite3"))
    monkeypatch.setenv("RESTORE_CONTEXT", "true" if restore else "false")
    if telemetry_url is not None:
        monkeypatch.setenv("TELEMETRY_API_URL", telemetry_url)
    else:
        monkeypatch.delenv("TELEMETRY_API_URL", raising=False)
    if persona_presets_file is not None:
        monkeypatch.setenv("PERSONA_PRESETS_FILE", str(persona_presets_file))
    else:
        monkeypatch.delenv("PERSONA_PRESETS_FILE", raising=False)
    if persona_default is not None:
        monkeypatch.setenv("PERSONA_DEFAULT", persona_default)
    else:
        monkeypatch.delenv("PERSONA_DEFAULT", raising=False)
    reload_app_config()
    module = importlib.import_module("apps.orchestrator.main")
    return importlib.reload(module)


def test_status_and_persona_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)
    with TestClient(module.app) as client:
        response = client.get("/status")
        assert response.status_code == 200
        data = response.json()
        assert data["persona"]["style"] == "kawaii"
        presets = data["persona_presets"]
        assert presets["active"] == "default"
        assert {"default", "cozy", "hype"}.issubset(set(presets["available"]))

        update = client.post("/persona", json={"style": "chaotic", "chaos_level": 0.8})
        assert update.status_code == 200
        update_payload = update.json()
        assert update_payload["active_preset"] == "custom"
        assert update_payload["persona"]["chaos_level"] == 0.8

        refreshed = client.get("/status")
        assert refreshed.status_code == 200
        payload = refreshed.json()
        persona = payload["persona"]
        assert persona["style"] == "chaotic"
        assert persona["chaos_level"] == 0.8
        assert payload["memory"]["restore_enabled"] is False
        assert payload["control"]["tts_muted"] is False
        assert payload["persona_presets"]["active"] == "custom"


def test_toggle_and_ingest_chat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)
    with TestClient(module.app) as client:
        result = client.post("/toggle/tts_worker", json={"enabled": False})
        assert result.status_code == 200
        payload = result.json()
        assert payload["module"] == "tts_worker"
        assert payload["enabled"] is False

        ingest = client.post(
            "/ingest/chat", json={"role": "user", "text": "Hello there!"}
        )
        assert ingest.status_code == 200
        assert ingest.json()["status"] == "accepted"

        refreshed = client.get("/status").json()
        assert refreshed["modules"]["tts_worker"]["state"] == "offline"
        assert refreshed["control"]["tts_muted"] is True


def test_chat_webui_endpoints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)

    async def _fake_pipeline(self, text: str, *, synthesize: bool = True):
        await self.record_turn("assistant", "test reply")
        return {
            "request_id": "req-local",
            "content": "<speech>Hello from Kitsu!</speech>",
            "meta": {"voice": "test"},
        }

    monkeypatch.setattr(
        module.OrchestratorState,
        "_run_policy_pipeline",
        _fake_pipeline,
        raising=False,
    )

    with TestClient(module.app) as client:
        chat = client.get("/webui/chat")
        assert chat.status_code == 200
        assert "<!DOCTYPE html>" in chat.text

        overlay = client.get("/webui/overlay")
        assert overlay.status_code == 200
        assert "<!DOCTYPE html>" in overlay.text

        result = client.post(
            "/chat/respond", json={"text": "ping", "play_tts": False}
        )
        assert result.status_code == 200
        payload = result.json()
        assert payload["status"] == "ok"
        assert payload["payload"]["content"].startswith("<speech>")


def test_control_endpoints(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)
    with TestClient(module.app) as client:
        panic = client.post("/control/panic", json={"reason": "Latency spike"})
        assert panic.status_code == 200 or panic.status_code == 202
        panic_payload = panic.json()
        assert panic_payload["type"] == "control.panic"

        mute = client.post("/control/mute", json={"muted": True})
        assert mute.status_code == 200
        assert mute.json()["muted"] is True

        preset = client.post("/control/preset", json={"preset": "cozy"})
        assert preset.status_code == 200
        assert preset.json()["preset"] == "cozy"

        snapshot = client.get("/status").json()
        assert snapshot["control"]["tts_muted"] is True
        assert snapshot["control"]["active_preset"] == "cozy"
        assert snapshot["persona"]["style"] == "calm"
        assert snapshot["persona_presets"]["active"] == "cozy"


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


def test_persona_presets_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    preset_file = tmp_path / "persona_presets.yaml"
    preset_file.write_text(
        textwrap.dedent(
            """
            mage:
              style: arcane
              chaos_level: 0.15
              energy: 0.4
              family_mode: true
              system_prompt: |
                You are Kitsu.exe the arcane librarian. Keep things thoughtful and a tiny bit mysterious.
            """
        ).strip()
    )
    module = load_orchestrator(
        monkeypatch,
        tmp_path,
        persona_presets_file=preset_file,
        persona_default="mage",
    )
    with TestClient(module.app) as client:
        status = client.get("/status").json()
    assert status["persona"]["style"] == "arcane"
    assert status["persona_presets"]["active"] == "mage"
    assert "mage" in status["persona_presets"]["available"]


def test_event_types_use_underscore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)
    module.state.memory.summary_interval = 1
    module.state.memory._count = 0  # ensure next turn produces a summary

    def expect_event(ws, expected_type: str) -> dict[str, Any]:
        for _ in range(5):
            message = ws.receive_json()
            if message["type"] == expected_type:
                return message
        raise AssertionError(f"Did not receive event type {expected_type}")

    with TestClient(module.app) as client:
        with client.websocket_connect("/stream") as websocket:
            status_event = expect_event(websocket, "status")
            assert "payload" in status_event

            client.post("/persona", json={"style": "calm", "energy": 0.7})
            persona_event = expect_event(websocket, "persona_update")
            assert persona_event["persona"]["style"] == "calm"

            client.post("/tts", json={"text": "Hello there!"})
            tts_event = expect_event(websocket, "tts_request")
            assert tts_event["data"]["text"] == "Hello there!"
            memory_event = expect_event(websocket, "memory_summary")
            assert "summary" in memory_event

            client.post("/obs/scene", json={"scene": "Live"})
            obs_event = expect_event(websocket, "obs_scene")
            assert obs_event["scene"] == "Live"

            client.post("/vts/expr", json={"expression": "smile", "intensity": 0.4})
            expr_event = expect_event(websocket, "vts_expression")
            assert expr_event["data"]["expression"] == "smile"


def test_chat_pipeline_hits_policy_and_tts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)

    async def fake_invoke_policy(payload: dict[str, Any], broker: Any) -> dict[str, Any]:
        await broker.publish({"type": "policy.token", "payload": {"token": "Hello"}})
        return {
            "content": "<speech>Hello chat!</speech>",
            "request_id": "req-123",
            "meta": {"voice": "kitsune"},
        }

    async def fake_invoke_tts(text: str, voice: Optional[str], request_id: Optional[str]):
        return {
            "audio_path": "artifacts/req-123.wav",
            "voice": voice or "kitsune",
            "latency_ms": 42.0,
            "cached": False,
        }

    monkeypatch.setattr(module, "_invoke_policy", fake_invoke_policy)
    monkeypatch.setattr(module, "_invoke_tts", fake_invoke_tts)

    with TestClient(module.app) as client:
        response = client.post("/chat/respond", json={"text": "ping", "play_tts": True})

    assert response.status_code == 200
    payload = response.json()["payload"]
    assert payload["content"].startswith("<speech>")
    status = module.state.snapshot()
    assert status["last_tts"]["voice"] == "kitsune"
    assert module.state.memory.buffer.as_list()[-1].role == "assistant"


def test_publish_sends_telemetry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _scenario() -> None:
        calls: list[dict[str, Any]] = []

        class DummyClient:
            def __init__(self, base_url: str, timeout: object) -> None:
                self.base_url = base_url
                self.timeout = timeout

            async def post(self, path: str, json: dict[str, Any]) -> None:
                calls.append({"path": path, "json": json})

            async def aclose(self) -> None:  # pragma: no cover - simple stub
                return

        module = load_orchestrator(
            monkeypatch, tmp_path, telemetry_url="https://telemetry.local"
        )
        monkeypatch.setattr(module.httpx, "AsyncClient", DummyClient)
        await module.telemetry.startup()

        await module.broker.publish(
            {"type": "persona_update", "payload": {"foo": "bar"}}
        )

        assert len(calls) == 1
        call = calls[0]
        assert call["path"] == "/events"
        payload = call["json"]
        assert isinstance(payload, dict)
        assert payload["type"] == "persona_update"
        assert isinstance(payload["ts"], float)
        assert payload["payload"] == {"foo": "bar"}

        await module.telemetry.shutdown()

    asyncio.run(_scenario())


def test_telemetry_retries_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def _scenario() -> None:
        attempts: list[int] = []
        events: list[dict[str, Any]] = []

        class FlakyClient:
            def __init__(self, base_url: str, timeout: object) -> None:
                self.base_url = base_url
                self.timeout = timeout
                self._calls = 0

            async def post(self, path: str, json: dict[str, Any]) -> None:
                self._calls += 1
                attempts.append(self._calls)
                if self._calls < 3:
                    raise RuntimeError("boom")
                events.append(json)

            async def aclose(self) -> None:  # pragma: no cover - simple stub
                return

        module = load_orchestrator(
            monkeypatch, tmp_path, telemetry_url="https://telemetry.local"
        )
        monkeypatch.setattr(module.httpx, "AsyncClient", FlakyClient)
        module.telemetry._retry_factory = lambda: AsyncRetrying(  # type: ignore[assignment]
            stop=stop_after_attempt(3),
            wait=wait_fixed(0),
            reraise=True,
        )
        await module.telemetry.startup()

        await module.broker.publish({"type": "status", "payload": {"ok": True}})

        assert attempts == [1, 2, 3]
        assert len(events) == 1
        assert events[0]["type"] == "status"
        await module.telemetry.shutdown()

    asyncio.run(_scenario())
