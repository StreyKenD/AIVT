from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from .utils import load_orchestrator, wait_for_event


@pytest.mark.asyncio()
async def test_toggle_endpoint_emits_module_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)
    token, queue = await module.broker.subscribe()
    try:
        transport = ASGITransport(app=module.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/toggle/tts_worker",
                json={"enabled": False},
                headers={"X-API-Key": "test-key"},
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["module"] == "tts_worker"
            assert payload["enabled"] is False

        event = await wait_for_event(queue, "module.toggle")
        assert event["module"] == "tts_worker"
        assert event["enabled"] is False
        assert module.state.modules["tts_worker"].enabled is False
    finally:
        await module.broker.unsubscribe(token)


@pytest.mark.asyncio()
async def test_panic_endpoint_updates_control_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = load_orchestrator(monkeypatch, tmp_path)
    token, queue = await module.broker.subscribe()
    try:
        transport = ASGITransport(app=module.app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/control/panic",
                json={"reason": "spilled tea"},
                headers={"X-API-Key": "test-key"},
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["type"] == "control.panic"

        event = await wait_for_event(queue, "control.panic")
        assert event["reason"] is None or event.get("reason") == "spilled tea"
        snapshot = module.state.snapshot()
        assert snapshot["control"]["panic_reason"] == "spilled tea"
    finally:
        await module.broker.unsubscribe(token)
