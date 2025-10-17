from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import Iterable, List

import pytest

import apps.asr_worker.runner as asr_runner
from apps.asr_worker import (
    ASRConfig,
    SpeechPipeline,
    Transcriber,
    VoiceActivityDetector,
)
from apps.asr_worker.devices import gather_devices


class _StubVAD(VoiceActivityDetector):
    def __init__(self, frame_bytes: int) -> None:
        self._frame_bytes = frame_bytes

    def is_speech(self, frame: bytes) -> bool:
        if len(frame) != self._frame_bytes:
            raise AssertionError("Frame size mismatch")
        return frame[0] == 1


class _StubTranscriber(Transcriber):
    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, audio: bytes):  # type: ignore[override]
        self.calls += 1
        suffix = "final" if self.calls > 1 else "partial"
        return SimpleNamespace(text=f"hello-{suffix}", confidence=0.9, language="en")


class _RecordingOrchestrator:
    def __init__(self) -> None:
        self.events: List[tuple[str, dict]] = []

    async def publish(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


def test_speech_pipeline_emits_partial_and_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _scenario() -> None:
        config = ASRConfig(
            model_name="tiny",  # unused in test
            orchestrator_url="http://localhost:8000",
            sample_rate=16000,
            frame_duration_ms=40,
            partial_interval_ms=50,
            silence_duration_ms=120,
            vad_mode="webrtc",
            vad_aggressiveness=2,
            input_device=None,
            fake_audio=False,
            device_preference="cpu",
            compute_type=None,
        )

        telemetry_calls: dict[str, list[dict]] = {"partial": [], "final": [], "skipped": []}

        class _TelemetryStub:
            async def segment_partial(
                self,
                *,
                segment: int,
                latency_ms: float,
                text: str,
                confidence,
                language,
            ) -> None:
                telemetry_calls["partial"].append(
                    {
                        "segment": segment,
                        "latency_ms": latency_ms,
                        "text_length": len(text),
                        "confidence": confidence,
                        "language": language,
                    }
                )

            async def segment_final(
                self,
                *,
                segment: int,
                duration_ms: float,
                confidence,
                language,
                text: str,
            ) -> None:
                telemetry_calls["final"].append(
                    {
                        "segment": segment,
                        "duration_ms": duration_ms,
                        "text_length": len(text),
                        "confidence": confidence,
                        "language": language,
                    }
                )

            async def segment_skipped(
                self,
                *,
                segment: int,
                reason: str,
                language,
                text_length: int,
            ) -> None:
                telemetry_calls["skipped"].append(
                    {
                        "segment": segment,
                        "reason": reason,
                        "language": language,
                        "text_length": text_length,
                    }
                )

        orchestrator = _RecordingOrchestrator()
        pipeline = SpeechPipeline(
            config=config,
            vad=_StubVAD(config.frame_bytes),
            transcriber=_StubTranscriber(),
            orchestrator=orchestrator,  # type: ignore[arg-type]
            telemetry=_TelemetryStub(),  # type: ignore[arg-type]
        )

        loop = asyncio.get_running_loop()

        async def _immediate_executor(_executor, func, *args):
            return func(*args)

        monkeypatch.setattr(
            loop, "run_in_executor", _immediate_executor
        )  # type: ignore[arg-type]

        async def _frames():
            speech = bytes([1]) + b"\x00" * (config.frame_bytes - 1)
            silence = b"\x00" * config.frame_bytes
            for _ in range(3):
                await asyncio.sleep(0.06)
                yield speech
            for _ in range(config.silence_threshold_frames + 1):
                await asyncio.sleep(0.06)
                yield silence

        await pipeline.process(_frames())

        event_types = [event for event, _ in orchestrator.events]
        assert "asr_partial" in event_types
        assert "asr_final" in event_types

        final_event = next(
            payload for event, payload in orchestrator.events if event == "asr_final"
        )
        assert final_event["text"] == "hello-final"
        assert final_event["duration_ms"] > 0
        assert telemetry_calls["partial"]
        assert telemetry_calls["final"]
        assert not telemetry_calls["skipped"]

    asyncio.run(_scenario())


def test_speech_pipeline_emits_final_when_stream_ends_mid_speech(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _scenario() -> None:
        config = ASRConfig(
            model_name="tiny",  # unused in test
            orchestrator_url="http://localhost:8000",
            sample_rate=16000,
            frame_duration_ms=40,
            partial_interval_ms=50,
            silence_duration_ms=160,
            vad_mode="webrtc",
            vad_aggressiveness=2,
            input_device=None,
            fake_audio=False,
            device_preference="cpu",
            compute_type=None,
        )

        orchestrator = _RecordingOrchestrator()
        pipeline = SpeechPipeline(
            config=config,
            vad=_StubVAD(config.frame_bytes),
            transcriber=_StubTranscriber(),
            orchestrator=orchestrator,  # type: ignore[arg-type]
        )

        loop = asyncio.get_running_loop()

        async def _immediate_executor(_executor, func, *args):
            return func(*args)

        monkeypatch.setattr(
            loop, "run_in_executor", _immediate_executor
        )  # type: ignore[arg-type]

        async def _frames():
            speech = bytes([1]) + b"\x00" * (config.frame_bytes - 1)
            for _ in range(4):
                await asyncio.sleep(0.06)
                yield speech

        await pipeline.process(_frames())

        event_types = [event for event, _ in orchestrator.events]
        assert event_types.count("asr_final") == 1
        final_event = orchestrator.events[-1][1]
        assert final_event["text"] == "hello-final"

    asyncio.run(_scenario())


def test_speech_pipeline_skips_non_english_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _scenario() -> None:
        config = ASRConfig(
            model_name="tiny",
            orchestrator_url="http://localhost:8000",
            sample_rate=16000,
            frame_duration_ms=20,
            partial_interval_ms=50,
            silence_duration_ms=120,
            vad_mode="webrtc",
            vad_aggressiveness=2,
            input_device=None,
            fake_audio=False,
            device_preference="cpu",
            compute_type=None,
        )

        telemetry_calls: dict[str, list[dict]] = {"partial": [], "final": [], "skipped": []}

        class _TelemetryStub:
            async def segment_partial(self, **_kwargs) -> None:
                telemetry_calls["partial"].append(_kwargs)

            async def segment_final(self, **_kwargs) -> None:
                telemetry_calls["final"].append(_kwargs)

            async def segment_skipped(self, **kwargs) -> None:
                telemetry_calls["skipped"].append(kwargs)

        class _SpanishTranscriber(Transcriber):
            def transcribe(self, audio: bytes):  # type: ignore[override]
                return SimpleNamespace(text="hola", confidence=0.8, language="es")

        orchestrator = _RecordingOrchestrator()
        pipeline = SpeechPipeline(
            config=config,
            vad=_StubVAD(config.frame_bytes),
            transcriber=_SpanishTranscriber(),
            orchestrator=orchestrator,  # type: ignore[arg-type]
            telemetry=_TelemetryStub(),  # type: ignore[arg-type]
        )

        loop = asyncio.get_running_loop()

        async def _immediate_executor(_executor, func, *args):
            return func(*args)

        monkeypatch.setattr(loop, "run_in_executor", _immediate_executor)  # type: ignore[arg-type]

        async def _frames():
            speech = bytes([1]) + b"\x00" * (config.frame_bytes - 1)
            silence = b"\x00" * config.frame_bytes
            for _ in range(3):
                await asyncio.sleep(0.02)
                yield speech
            for _ in range(config.silence_threshold_frames + 1):
                await asyncio.sleep(0.02)
                yield silence

        await pipeline.process(_frames())

        assert not orchestrator.events, "Non-English segments should not reach orchestrator"
        assert not telemetry_calls["partial"]
        assert not telemetry_calls["final"]
        assert telemetry_calls["skipped"]

    asyncio.run(_scenario())


class _SoundDeviceStub:
    def __init__(self) -> None:
        self.default = SimpleNamespace(device=(1, 0))

    def query_devices(self) -> Iterable[dict]:
        return [
            {"name": "Mic 1", "max_input_channels": 0, "hostapi": 0},
            {"name": "Mic 2", "max_input_channels": 1, "hostapi": 0},
            {"name": "Mic 3", "max_input_channels": 2, "hostapi": 1},
        ]

    def query_hostapis(self) -> Iterable[dict]:
        return [
            {"name": "WASAPI"},
            {"name": "MME"},
        ]


class _PyAudioInstanceStub:
    def __init__(self) -> None:
        self._terminated = False

    def get_device_count(self) -> int:
        return 3

    def get_device_info_by_index(self, index: int) -> dict:
        mapping = {
            0: {"name": "Loopback", "maxInputChannels": 0, "hostApi": "WASAPI"},
            1: {"name": "Focusrite", "maxInputChannels": 2, "hostApi": "ASIO"},
            2: {"name": "USB Mic", "maxInputChannels": 1, "hostApi": "WDM"},
        }
        return mapping[index]

    def get_default_input_device_info(self) -> dict:
        return {"index": 2}

    def terminate(self) -> None:
        self._terminated = True


class _PyAudioModuleStub:
    def __init__(self) -> None:
        self.instance = _PyAudioInstanceStub()

    def PyAudio(self):  # type: ignore[override]
        return self.instance


def test_gather_devices_merges_backends() -> None:
    entries = gather_devices(
        sounddevice=_SoundDeviceStub(), pyaudio=_PyAudioModuleStub()
    )
    assert entries
    names = {entry.name for entry in entries}
    assert {"Mic 2", "Mic 3", "Focusrite", "USB Mic"}.issubset(names)
    default_entries = [entry for entry in entries if entry.is_default]
    assert any(entry.backend == "sounddevice" for entry in default_entries)
    assert any(entry.backend == "pyaudio" for entry in default_entries)


def test_gather_devices_handles_missing_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "apps.asr_worker.devices.load_module_if_available", lambda _name: None
    )
    entries = gather_devices(sounddevice=None, pyaudio=None)
    assert entries == []


def test_run_worker_retries_after_pipeline_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _scenario() -> None:
        config = ASRConfig(
            model_name="tiny",
            orchestrator_url="http://localhost:8000",
            sample_rate=16000,
            frame_duration_ms=20,
            partial_interval_ms=100,
            silence_duration_ms=200,
            vad_mode="webrtc",
            vad_aggressiveness=2,
            input_device=None,
            fake_audio=False,
            device_preference="cpu",
            compute_type=None,
        )

        attempts = 0
        resumed = asyncio.Event()

        class _StubOrchestrator:
            def __init__(self, _url: str) -> None:
                self.closed = False

            async def publish(self, event_type: str, payload: dict) -> None:
                return None

            async def aclose(self) -> None:
                self.closed = True

        telemetry_records: dict[str, list[tuple[int, str]]] = {
            "started": [],
            "completed": [],
        }

        class _TelemetryStub:
            async def aclose(self) -> None:
                return None

            async def cycle_started(
                self, attempt: int, backoff_seconds: float
            ) -> None:
                telemetry_records["started"].append(
                    (attempt, f"{backoff_seconds:.1f}")
                )

            async def cycle_completed(
                self, attempt: int, outcome: str, *, detail: str | None = None
            ) -> None:
                telemetry_records["completed"].append((attempt, outcome))

            async def segment_partial(self, **_kwargs) -> None:
                return None

            async def segment_final(self, **_kwargs) -> None:
                return None

        monkeypatch.setattr(asr_runner, "OrchestratorClient", _StubOrchestrator)
        monkeypatch.setattr(asr_runner, "build_transcriber", lambda _cfg: object())
        monkeypatch.setattr(asr_runner, "build_vad", lambda _cfg: object())
        monkeypatch.setattr(asr_runner, "create_telemetry", lambda: _TelemetryStub())

        @contextlib.asynccontextmanager
        async def _fake_audio_source(_cfg: ASRConfig):
            class _Source:
                def frames(self):
                    async def _gen():
                        while True:
                            yield b"\x00" * _cfg.frame_bytes
                            await asyncio.sleep(_cfg.frame_duration_ms / 1000)

                    return _gen()

            yield _Source()

        monkeypatch.setattr(asr_runner, "acquire_audio_source", _fake_audio_source)

        class _StubPipeline:
            def __init__(
                self,
                *,
                config: ASRConfig,
                vad: object,
                transcriber: object,
                orchestrator: object,
                telemetry: object,
            ) -> None:
                self._config = config
                self._orchestrator = orchestrator

            async def process(self, frames) -> None:
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise asyncio.CancelledError()
                resumed.set()
                await asyncio.sleep(0)

        monkeypatch.setattr(asr_runner, "SpeechPipeline", _StubPipeline)

        worker_task = asyncio.create_task(asr_runner.run_worker(config))
        await asyncio.wait_for(resumed.wait(), timeout=2.5)
        worker_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker_task
        assert attempts >= 2
        assert telemetry_records["started"]
        assert telemetry_records["completed"]

    asyncio.run(_scenario())
