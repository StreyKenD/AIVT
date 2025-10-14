from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator, List, Tuple

from apps.asr_worker.main import ASRConfig, SpeechPipeline, TranscriptionResult


class DummyTranscriber:
    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, audio: bytes) -> TranscriptionResult:
        self.calls += 1
        if self.calls == 1:
            return TranscriptionResult(text="hello", confidence=0.9, language="en")
        return TranscriptionResult(text="hello world", confidence=0.92, language="en")


class PatternVAD:
    def __init__(self, decisions: List[bool], frame_bytes: int) -> None:
        self._decisions = decisions
        self._frame_bytes = frame_bytes
        self._index = 0

    def is_speech(self, frame: bytes) -> bool:
        assert len(frame) == self._frame_bytes
        decision = self._decisions[min(self._index, len(self._decisions) - 1)]
        self._index += 1
        return decision


@dataclass
class Recorder:
    events: List[Tuple[str, dict]]

    async def publish(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


async def iter_frames(frames: List[bytes], delay: float) -> AsyncIterator[bytes]:
    for frame in frames:
        yield frame
        await asyncio.sleep(delay)


def test_pipeline_emits_partial_and_final_events() -> None:
    async def _scenario() -> None:
        config = ASRConfig(
            model_name="tiny.en",
            orchestrator_url="http://localhost:8000",
            sample_rate=16000,
            frame_duration_ms=20,
            partial_interval_ms=80,
            silence_duration_ms=120,
            vad_mode="webrtc",
            vad_aggressiveness=2,
            input_device=None,
            fake_audio=False,
            device_preference="cpu",
            compute_type="int8",
        )
        frame = b"\x01\x00" * config.frame_samples
        silence = b"\x00\x00" * config.frame_samples
        frames = [frame] * 8 + [silence] * (config.silence_threshold_frames + 2)
        vad = PatternVAD(
            [True] * 8 + [False] * (config.silence_threshold_frames + 2),
            config.frame_bytes,
        )
        recorder = Recorder(events=[])
        pipeline = SpeechPipeline(
            config=config,
            vad=vad,
            transcriber=DummyTranscriber(),
            orchestrator=recorder,
        )
        await pipeline.process(
            iter_frames(frames, delay=config.frame_duration_ms / 1000)
        )

        recorded = recorder.events
        assert any(event[0] == "asr_partial" for event in recorded)
        assert any(event[0] == "asr_final" for event in recorded)
        final_events = [payload for event, payload in recorded if event == "asr_final"]
        assert final_events, "Expected at least one final event"
        assert final_events[0]["text"] == "hello world"
        assert final_events[0]["duration_ms"] > 0

    asyncio.run(_scenario())
