from __future__ import annotations

import asyncio
import logging
import os
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("kitsu.tts")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


@dataclass
class TTSJob:
    text: str
    voice: Optional[str]
    future: asyncio.Future["TTSResult"]


@dataclass
class TTSResult:
    audio_path: Path
    visemes: List[Dict[str, float]]
    voice: Optional[str]


class TTSService:
    """Stub implementation that emulates Coqui-TTS with Piper fallback."""

    def __init__(self) -> None:
        self.model_name = os.getenv("TTS_MODEL_NAME", "coqui-tts-kawaii")
        self.backup = os.getenv("TTS_BACKUP", "Piper")
        self.output_dir = Path(os.getenv("TTS_OUTPUT_DIR", "artifacts/tts"))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._queue: asyncio.Queue[TTSJob] = asyncio.Queue()

    async def enqueue(self, text: str, voice: Optional[str]) -> TTSResult:
        loop = asyncio.get_running_loop()
        future: "asyncio.Future[TTSResult]" = loop.create_future()
        await self._queue.put(TTSJob(text=text, voice=voice, future=future))
        return await future

    async def worker(self) -> None:
        logger.info(
            "TTS worker ready (model=%s, backup=%s)", self.model_name, self.backup
        )
        while True:
            job = await self._queue.get()
            try:
                result = await self._synthesize(job.text, job.voice)
                job.future.set_result(result)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("TTS synthesis failed: %s", exc)
                job.future.set_exception(exc)

    async def _synthesize(self, text: str, voice: Optional[str]) -> TTSResult:
        duration = max(1.0, min(6.0, len(text) / 12))
        sample_rate = 22050
        total_frames = int(sample_rate * duration)
        audio_path = self.output_dir / f"tts_{abs(hash((text, voice)))}.wav"
        silence_frame = (0).to_bytes(2, "little", signed=True)
        with wave.open(str(audio_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(silence_frame * total_frames)
        visemes = self._viseme_from_text(text, duration)
        logger.info("Generated TTS output path=%s voice=%s", audio_path, voice)
        return TTSResult(
            audio_path=audio_path, visemes=visemes, voice=voice or self.model_name
        )

    def _viseme_from_text(self, text: str, duration: float) -> List[Dict[str, float]]:
        step = max(duration / max(len(text), 1), 0.05)
        values: List[Dict[str, float]] = []
        t = 0.0
        for ch in text:
            energy = 0.2 if ch == " " else min(1.0, 0.4 + (ord(ch) % 30) / 100)
            values.append({"time": round(t, 2), "rms": round(energy, 2)})
            t += step
        if not values:
            values.append({"time": 0.0, "rms": 0.3})
        return values


_service: Optional[TTSService] = None


def get_tts_service() -> TTSService:
    global _service
    if _service is None:
        _service = TTSService()
    return _service
