import asyncio
import importlib
import json
import time
from typing import Any, Dict

import httpx
import pytest


module = importlib.import_module("apps.soak_harness.main")
SoakHarness = module.SoakHarness
_extract_speech_text = module._extract_speech_text


class StubTelemetryClient:
    def __init__(self) -> None:
        self.events: list[tuple[str, Dict[str, Any]]] = []

    async def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.events.append((event_type, payload))


def test_soak_harness_collects_summary() -> None:
    def orch_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/ingest/chat":
            body = json.loads(request.content.decode())
            assert body["text"]
            return httpx.Response(200, json={"status": "accepted"})
        if request.method == "POST" and request.url.path == "/tts":
            body = json.loads(request.content.decode())
            assert body["text"]
            return httpx.Response(
                200,
                json={
                    "type": "tts_request",
                    "data": {"text": body["text"], "voice": None, "ts": time.time()},
                },
            )
        if request.method == "GET" and request.url.path == "/status":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "persona": {
                        "style": "kawaii",
                        "chaos_level": 0.2,
                        "energy": 0.5,
                        "family_mode": True,
                    },
                    "modules": {
                        "asr_worker": {"state": "online", "latency_ms": 10.0},
                        "policy_worker": {"state": "online", "latency_ms": 20.0},
                        "tts_worker": {"state": "online", "latency_ms": 30.0},
                    },
                },
            )
        raise AssertionError(
            f"Unexpected orchestrator request: {request.method} {request.url}"
        )

    policy_payload = (
        "event: start\n"
        "data: {}\n\n"
        "event: final\n"
        'data: {"content": "<speech>hello</speech><mood>kawaii</mood>", "latency_ms": 42.0, "source": "ollama"}\n\n'
    )

    def policy_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/respond"
        stream = httpx.ByteStream(policy_payload.encode("utf-8"))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    def telemetry_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/metrics/latest"
        return httpx.Response(
            200,
            json={
                "window_seconds": 300,
                "metrics": {
                    "policy_worker": {"count": 1, "latency_ms": {"avg": 40.0}},
                },
            },
        )

    async def _run() -> tuple[Dict[str, Any], list[tuple[str, Dict[str, Any]]]]:
        orch_client = httpx.AsyncClient(
            transport=httpx.MockTransport(orch_handler), base_url="http://orch"
        )
        policy_client = httpx.AsyncClient(
            transport=httpx.MockTransport(policy_handler), base_url="http://policy"
        )
        telemetry_http = httpx.AsyncClient(
            transport=httpx.MockTransport(telemetry_handler),
            base_url="http://telemetry",
        )
        telemetry_client = StubTelemetryClient()

        harness = SoakHarness(
            "http://orch",
            "http://policy",
            telemetry_url="http://telemetry",
            orchestrator_client=orch_client,
            policy_client=policy_client,
            telemetry_client=telemetry_client,
            telemetry_http_client=telemetry_http,
        )

        summary = await harness.run(
            duration_minutes=0.01, max_turns=1, turn_interval=0.0, warmup_turns=0
        )

        await orch_client.aclose()
        await policy_client.aclose()
        await telemetry_http.aclose()

        return summary, telemetry_client.events

    summary, events = asyncio.run(_run())

    assert summary["success"] is True
    assert summary["turns"] == 1
    assert summary["policy_latency_ms"]["avg"] == pytest.approx(42.0)
    assert "telemetry_metrics" in summary
    assert events and events[0][0] == "soak.result"


def test_extract_speech_text_handles_missing_tags() -> None:
    assert _extract_speech_text("sem tags") == "sem tags"
    assert _extract_speech_text("<speech>  hello\nworld  </speech>") == "hello world"
