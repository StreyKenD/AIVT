from __future__ import annotations

import asyncio
import importlib
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict

import pytest
from httpx import ASGITransport, AsyncClient

from libs.config import reload_app_config
from libs.contracts.asr import ASRFinalEvent, ASRPartialEvent
from apps.asr_worker import ASRConfig, SpeechPipeline, TranscriptionResult
from apps.asr_worker.metrics import ASRTelemetry


pytest.importorskip("fastapi", reason="orchestrator depends on FastAPI")


class _StubTelemetry(ASRTelemetry):
    def __init__(self) -> None:
        super().__init__(client=None)

    async def cycle_started(self, attempt: int, backoff_seconds: float) -> None:
        return None

    async def cycle_completed(
        self, attempt: int, outcome: str, *, detail: str | None = None
    ) -> None:
        return None


class _StubTranscriber:
    def __init__(self) -> None:
        self._calls = 0

    def transcribe(self, audio: bytes) -> TranscriptionResult:
        self._calls += 1
        if self._calls == 1:
            return TranscriptionResult(
                text="integration partial", confidence=0.9, language="en"
            )
        return TranscriptionResult(
            text="integration final", confidence=0.92, language="en"
        )


class _DeterministicVAD:
    def __init__(self, frame_bytes: int, speech_frames: int) -> None:
        self._frame_bytes = frame_bytes
        self._remaining = speech_frames

    def is_speech(self, frame: bytes) -> bool:
        assert len(frame) == self._frame_bytes
        if self._remaining > 0:
            self._remaining -= 1
            return True
        return False


@asynccontextmanager
async def _scripted_frames(config: ASRConfig) -> AsyncIterator[AsyncIterator[bytes]]:
    speech_frames = 6
    silence_frames = config.silence_threshold_frames + 1
    speech_chunk = b"\x01\x00" * config.frame_samples
    silence_chunk = b"\x00\x00" * config.frame_samples

    async def _generator() -> AsyncIterator[bytes]:
        for _ in range(speech_frames):
            await asyncio.sleep(config.frame_duration_ms / 1000)
            yield speech_chunk
        for _ in range(silence_frames):
            await asyncio.sleep(config.frame_duration_ms / 1000)
            yield silence_chunk

    yield _generator()


class _HTTPPublisher:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def publish(self, event: ASRPartialEvent | ASRFinalEvent) -> None:
        await self._client.post("/events/asr", json=event.model_dump())


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_pipeline_posts_events_to_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reload_app_config()
    module = importlib.reload(importlib.import_module("apps.orchestrator.main"))
    app = module.app
    broker = module.broker

    token, queue = await broker.subscribe()

    try:
        config = ASRConfig(
            model_name="tiny",
            orchestrator_url="http://testserver",
            sample_rate=16000,
            frame_duration_ms=20,
            partial_interval_ms=80,
            silence_duration_ms=200,
            vad_mode="none",
            vad_aggressiveness=0,
            input_device=None,
            fake_audio=False,
            device_preference="cpu",
            compute_type="int8",
        )

        vad = _DeterministicVAD(config.frame_bytes, speech_frames=6)
        transcriber = _StubTranscriber()
        telemetry = _StubTelemetry()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url=config.orchestrator_url
        ) as client, _scripted_frames(config) as frames:
            publisher = _HTTPPublisher(client)
            pipeline = SpeechPipeline(
                config=config,
                vad=vad,
                transcriber=transcriber,
                orchestrator=publisher,
                telemetry=telemetry,
            )

            loop = asyncio.get_running_loop()

            async def _immediate(_executor, func, *args):
                return func(*args)

            monkeypatch.setattr(loop, "run_in_executor", _immediate)  # type: ignore[arg-type]

            await pipeline.process(frames)

        observed: Dict[str, dict] = {}
        while len(observed) < 2:
            event = await asyncio.wait_for(queue.get(), timeout=5.0)
            event_type = event.get("type")
            if (
                event_type in {"asr_partial", "asr_final"}
                and event_type not in observed
            ):
                observed[event_type] = event["payload"]

        assert observed["asr_partial"]["text"] == "integration partial"
        assert observed["asr_final"]["text"] == "integration final"
    finally:
        await broker.unsubscribe(token)
