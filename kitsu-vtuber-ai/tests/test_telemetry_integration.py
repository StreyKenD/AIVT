import asyncio
import importlib
import json
from typing import List, Tuple

import pytest

from apps.tts_worker.service import TTSService


class StubTelemetry:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, dict]] = []

    async def publish(self, event_type: str, payload: dict) -> None:
        self.calls.append((event_type, payload))


def test_tts_service_emits_metrics(monkeypatch, tmp_path) -> None:
    async def _scenario() -> None:
        monkeypatch.setenv("TTS_DISABLE_COQUI", "1")
        monkeypatch.setenv("TTS_DISABLE_PIPER", "1")
        monkeypatch.setenv("TTS_OUTPUT_DIR", str(tmp_path))
        telemetry = StubTelemetry()
        service = TTSService(telemetry=telemetry)
        worker = asyncio.create_task(service.worker())
        try:
            result = await asyncio.wait_for(
                service.enqueue("konnichiwa chat"), timeout=5
            )
            assert result.cached is False
            await asyncio.sleep(0)
            assert telemetry.calls, "Expected telemetry metric"
            event_type, payload = telemetry.calls[0]
            assert event_type == "tts.completed"
            assert payload["status"] == "ok"
            assert payload["cached"] is False
            assert payload["text_length"] == len("konnichiwa chat")
        finally:
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker

    asyncio.run(_scenario())


def test_policy_generator_emits_metrics(monkeypatch) -> None:
    pytest.importorskip("fastapi", reason="policy worker depende de FastAPI")

    async def _scenario() -> None:
        module = importlib.import_module("apps.policy_worker.main")
        module = importlib.reload(module)
        telemetry = StubTelemetry()
        monkeypatch.setattr(module, "TELEMETRY", telemetry, raising=False)

        lines = [
            json.dumps(
                {
                    "message": {
                        "role": "assistant",
                        "content": "<speech>ola chat</speech>",
                    },
                    "done": False,
                }
            ),
            json.dumps(
                {
                    "message": {
                        "role": "assistant",
                        "content": "<mood>kawaii</mood>",
                    },
                    "done": False,
                }
            ),
            json.dumps(
                {
                    "message": {
                        "role": "assistant",
                        "content": "<actions>wave</actions>",
                    },
                    "done": False,
                }
            ),
            json.dumps({"done": True, "total_duration": 1_000_000, "eval_count": 10}),
        ]

        class _StubStream:
            def __init__(self, payload: List[str]) -> None:
                self._payload = payload

            async def __aenter__(self) -> "_StubStream":
                return self

            async def __aexit__(
                self,
                exc_type,
                exc,
                tb,
            ) -> None:  # pragma: no cover - nothing to clean
                return None

            def raise_for_status(self) -> None:
                return None

            async def aiter_lines(self):
                for item in self._payload:
                    yield item

        class _StubClient:
            def __init__(self, **_: object) -> None:
                pass

            async def __aenter__(self) -> "_StubClient":
                return self

            async def __aexit__(
                self,
                exc_type,
                exc,
                tb,
            ) -> None:  # pragma: no cover - nothing to clean
                return None

            def stream(self, *_: object, **__: object) -> _StubStream:
                return _StubStream(lines)

        monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: _StubClient())

        payload = module.PolicyRequest(
            text="hello there",
            persona_style="kawaii",
            chaos_level=0.3,
            energy=0.6,
            recent_turns=[],
        )

        chunks: List[str] = []
        async for chunk in module.policy_event_generator(payload):
            chunks.append(chunk)
        assert any("final" in chunk for chunk in chunks)

        assert telemetry.calls, "Expected policy telemetry metric"
        event_type, metric = telemetry.calls[0]
        assert event_type == "policy.response"
        assert metric["status"] == "ok"
        assert metric["source"] == "ollama"
        assert metric["text_length"] == len(payload.text)
        assert metric["retries"] == 0

    asyncio.run(_scenario())
