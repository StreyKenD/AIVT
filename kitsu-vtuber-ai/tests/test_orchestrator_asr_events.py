from __future__ import annotations

import asyncio
import importlib
import time
from types import ModuleType

import pytest
from httpx import ASGITransport, AsyncClient


pytest.importorskip("fastapi", reason="orquestrador depende de FastAPI")


def test_receive_asr_event_publishes_to_broker_and_updates_state() -> None:
    async def _scenario() -> None:
        module = importlib.reload(importlib.import_module("apps.orchestrator.main"))
        assert isinstance(module, ModuleType)
        token, queue = await module.broker.subscribe()
        try:
            transport = ASGITransport(app=module.app)
            async with AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                now = time.time()
                payload = {
                    "type": "asr_final",
                    "segment": 1,
                    "text": "hello world",
                    "confidence": 0.9,
                    "language": "en",
                    "started_at": now - 0.5,
                    "ended_at": now,
                    "duration_ms": 500.0,
                }
                response = await client.post("/events/asr", json=payload)
                assert response.status_code == 200
                assert response.json()["status"] == "accepted"
                message = await asyncio.wait_for(queue.get(), timeout=2.0)
                assert message["type"] == "asr_final"
                assert message["payload"]["text"] == "hello world"
            module_state = module.state.modules["asr_worker"]
            assert module_state.latency_ms >= 1.0
            assert abs(module_state.last_updated - now) < 5.0
        finally:
            await module.broker.unsubscribe(token)

    asyncio.run(_scenario())
