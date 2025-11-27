from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from httpx import ASGITransport, AsyncClient

from libs.config import reload_app_config


def load_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    orchestrator_api_key: Optional[str] = None,
) -> Any:
    monkeypatch.setenv("MEMORY_DB_PATH", str(tmp_path / "memory.sqlite3"))
    monkeypatch.setenv("RESTORE_CONTEXT", "false")
    monkeypatch.delenv("TELEMETRY_API_URL", raising=False)
    monkeypatch.delenv("TELEMETRY_API_KEY", raising=False)
    if orchestrator_api_key is not None:
        monkeypatch.setenv("ORCHESTRATOR_API_KEY", orchestrator_api_key)
    else:
        monkeypatch.delenv("ORCHESTRATOR_API_KEY", raising=False)
    monkeypatch.delenv("PERSONA_PRESETS_FILE", raising=False)
    monkeypatch.delenv("PERSONA_DEFAULT", raising=False)
    reload_app_config()
    module = importlib.import_module("apps.orchestrator.main")
    return importlib.reload(module)


@pytest.mark.asyncio()
async def test_mocked_pipeline_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)

    tts_calls: List[Dict[str, Any]] = []

    async def fake_policy(
        payload: Dict[str, Any],
        broker: Any,
        stream_handler: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if stream_handler is not None:
            await stream_handler(
                "start",
                {"request_id": "req-e2e", "is_final_request": payload.get("is_final", True)},
            )
        await broker.publish({"type": "policy.token", "payload": {"token": "demo"}})
        return {
            "content": "<speech>Hello friend!</speech>",
            "meta": {"status": "ok", "voice": "demo_voice"},
            "request_id": "req-e2e",
        }

    async def fake_tts(
        text: str, voice: Optional[str], request_id: Optional[str]
    ) -> Dict[str, Any]:
        tts_calls.append({"text": text, "voice": voice, "request_id": request_id})
        return {
            "voice": voice or "default",
            "audio_path": "/tmp/fake.wav",
            "request_id": request_id,
        }

    module.state._policy_invoker = fake_policy  # type: ignore[attr-defined]
    module.state._tts_invoker = fake_tts  # type: ignore[attr-defined]

    events: List[Dict[str, Any]] = []
    token, queue = await module.broker.subscribe()
    try:
        transport = ASGITransport(app=module.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/chat/respond", json={"text": "Hey pipeline!", "play_tts": True}
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "ok"

        while True:
            event = await asyncio.wait_for(queue.get(), timeout=2.0)
            events.append(event)
            if event["type"] == "tts_generated":
                break
    finally:
        await module.broker.unsubscribe(token)

    assert any(event["type"] == "policy_final" for event in events)
    assert any(event["type"] == "tts_generated" for event in events)
    assert tts_calls
    assert tts_calls[0]["text"] == "Hello friend!"
    assert tts_calls[0]["request_id"] == "req-e2e"
