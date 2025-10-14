from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pytest

soak_module = importlib.import_module("apps.soak_harness.main")
SoakHarness = soak_module.SoakHarness


def test_windows_stack_scripts_cover_all_services() -> None:
    scripts_root = Path(__file__).resolve().parents[1] / "scripts"
    run_all = scripts_root / "run_all_no_docker.ps1"
    assert run_all.exists(), "run_all_no_docker.ps1 deve estar presente"
    content = run_all.read_text(encoding="utf-8")

    expected = [
        "run_orchestrator.ps1",
        "run_asr.ps1",
        "run_policy.ps1",
        "run_tts.ps1",
        "run_twitch.ps1",
        "run_obs.ps1",
        "run_vts.ps1",
    ]
    for script in expected:
        assert script in content, f"{script} não referenciado em run_all_no_docker.ps1"
        assert (scripts_root / script).exists(), f"{script} ausente em scripts/"

    assert 'ValidateSet("start", "stop", "status")' in content


class _FakeResponse:
    def __init__(self, json_payload: Dict[str, Any] | None = None) -> None:
        self._json = json_payload or {}

    def raise_for_status(
        self,
    ) -> None:  # pragma: no cover - mantido para compatibilidade
        return

    def json(self) -> Dict[str, Any]:
        return self._json


class _MockOrchestratorClient:
    def __init__(self) -> None:
        self.ingest_payloads: List[Dict[str, Any]] = []
        self.tts_payloads: List[Dict[str, Any]] = []

    async def post(
        self, path: str, json: Dict[str, Any], headers: Dict[str, str] | None = None
    ):
        if path == "/ingest/chat":
            self.ingest_payloads.append(json)
            return _FakeResponse({"status": "accepted"})
        if path == "/tts":
            self.tts_payloads.append(json)
            return _FakeResponse({"status": "queued"})
        raise AssertionError(f"Caminho inesperado: {path}")

    async def get(self, path: str, headers: Dict[str, str] | None = None):
        if path == "/status":
            payload = {
                "modules": {
                    "asr_worker": {"state": "online"},
                    "policy_worker": {"state": "online"},
                    "tts_worker": {"state": "online"},
                },
                "persona": {
                    "style": "kawaii",
                    "chaos_level": 0.2,
                    "energy": 0.6,
                    "family_mode": True,
                },
            }
            return _FakeResponse(payload)
        raise AssertionError(f"GET inesperado: {path}")

    async def aclose(self) -> None:
        return


class _MockPolicyStream:
    def __init__(self, events: Iterable[str]) -> None:
        self._events = list(events)

    async def __aenter__(self) -> "_MockPolicyStream":
        return self

    async def __aexit__(
        self, exc_type, exc, tb
    ) -> None:  # pragma: no cover - não utilizado
        return None

    def raise_for_status(self) -> None:
        return

    async def aiter_lines(self):
        for entry in self._events:
            yield entry


class _MockPolicyClient:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def stream(self, method: str, path: str, json: Dict[str, Any]):
        assert method == "POST" and path == "/respond"
        self.calls.append(json)
        payload = [
            "event: start",
            "data: {}",
            "",
            "event: final",
            'data: {"content": "<speech>olá</speech>", "latency_ms": 420.0, "source": "ollama"}',
            "",
        ]
        return _MockPolicyStream(payload)

    async def aclose(self) -> None:
        return


class _RecorderTelemetryClient:
    def __init__(self) -> None:
        self.events: List[tuple[str, Dict[str, Any]]] = []

    async def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.events.append((event_type, payload))


def test_round_trip_acceptance(monkeypatch: pytest.MonkeyPatch) -> None:
    orch = _MockOrchestratorClient()
    policy = _MockPolicyClient()
    telemetry = _RecorderTelemetryClient()

    perf_values = iter([0.0, 0.35, 0.35, 0.7])
    monkeypatch.setattr(soak_module.time, "perf_counter", lambda: next(perf_values))

    async def _run() -> Dict[str, Any]:
        harness = SoakHarness(
            "http://orch",
            "http://policy",
            orchestrator_client=orch,
            policy_client=policy,
            telemetry_client=telemetry,
        )

        return await harness.run(
            duration_minutes=0.01,
            max_turns=1,
            turn_interval=0.0,
            warmup_turns=0,
        )

    summary = asyncio.run(_run())

    assert summary["success"] is True
    assert summary["turns"] == 1
    avg_latency = summary["tts_latency_ms"]["avg"]
    assert avg_latency is not None and avg_latency <= 700
    assert summary["policy_latency_ms"]["avg"] == pytest.approx(420.0)

    assert telemetry.events, "telemetria não recebeu publicação"
    event_type, payload = telemetry.events[0]
    assert event_type == "soak.result"
    assert payload["success"] is True
    assert payload["tts_latency_ms"]["avg"] == avg_latency

    assert orch.ingest_payloads and orch.tts_payloads
    assert policy.calls[0]["text"]
