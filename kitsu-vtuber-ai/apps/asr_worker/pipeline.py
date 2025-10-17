from __future__ import annotations

import asyncio
import os
import time
from typing import Any, AsyncIterator, Dict, Optional

from .config import ASRConfig
from .logger import logger
from .metrics import ASRTelemetry
from .orchestrator import OrchestratorPublisher
from .transcription import Transcriber
from .vad import VoiceActivityDetector

DEFAULT_ENERGY_THRESHOLD = float(
    os.getenv("ASR_ENERGY_THRESHOLD", "300.0")
)  # pragma: no mutate


class SimpleASRPipeline:
    def __init__(
        self,
        config: ASRConfig,
        transcriber: Transcriber,
        *,
        vad: VoiceActivityDetector | None = None,
        energy_threshold: float = DEFAULT_ENERGY_THRESHOLD,
        min_duration_ms: int = 0,
        silence_duration_ms: Optional[int] = None,
        allow_non_english: bool | None = None,
        orchestrator: OrchestratorPublisher | None = None,
        telemetry: ASRTelemetry | None = None,
    ) -> None:
        self._config = config
        self._transcriber = transcriber
        self._buffer = bytearray()
        self._speech_active = False
        self._segment_started = 0.0
        self._silence_frames = 0
        self._segment_index = 0
        self._last_partial_at = 0.0
        self._last_partial_text = ""
        self._energy_threshold = energy_threshold
        self._min_duration = max(0, min_duration_ms)
        silence_ms = silence_duration_ms or config.silence_duration_ms
        self._silence_required = max(
            1,
            int(
                (silence_ms + config.frame_duration_ms - 1)
                // config.frame_duration_ms
            ),
        )
        env_flag = os.getenv("ASR_ALLOW_NON_ENGLISH", "0")
        self._allow_non_english = (
            allow_non_english
            if allow_non_english is not None
            else env_flag.lower() in {"1", "true", "yes"}
        )
        if self._allow_non_english:
            logger.debug("ASR pipeline allowing all languages for transcripts")
        self._partial_interval = max(config.partial_interval_ms / 1000, 0.05)
        self._min_partial_window = max(0.1, config.frame_duration_ms / 1000)
        self._orchestrator = orchestrator
        self._telemetry = telemetry
        self._vad = vad

    async def run(self, frames: AsyncIterator[bytes]) -> None:
        try:
            async for frame in frames:
                await self._handle_frame(frame)
        except asyncio.CancelledError:
            raise
        else:
            speech_active = self._speech_active
            buffered = bool(self._buffer)
            if speech_active and buffered:
                await self._emit_segment()
                self._reset_segment_state()
            else:
                await self._flush_active_segment()
            if speech_active:
                if buffered:
                    logger.warning(
                        "Audio frame stream finished while speech active; emitted final segment"
                    )
                else:
                    logger.warning(
                        "Audio frame stream finished while speech active; waiting for next capture cycle"
                    )
            else:
                logger.warning(
                    "Audio frame stream finished; waiting for next capture cycle"
                )

    async def process(self, frames: AsyncIterator[bytes]) -> None:
        """Backward-compatible alias for legacy callers/tests."""

        await self.run(frames)

    async def _handle_frame(self, frame: bytes) -> None:
        if len(frame) != self._config.frame_bytes:
            frame = frame[: self._config.frame_bytes].ljust(
                self._config.frame_bytes, b"\x00"
            )
        if self._is_silence(frame):
            await self._on_silence()
            return
        await self._on_speech(frame)

    async def _on_speech(self, frame: bytes) -> None:
        if not self._speech_active:
            self._speech_active = True
            self._buffer.clear()
            self._segment_started = time.time()
            self._segment_index += 1
            logger.debug("Speech segment %s started", self._segment_index)
        self._buffer.extend(frame)
        self._silence_frames = 0
        now = time.time()
        if now - self._segment_started < self._min_partial_window:
            return
        if (
            self._last_partial_at
            and now - self._last_partial_at < self._partial_interval
        ):
            return
        if self._orchestrator is None and self._telemetry is None:
            return
        await self._emit_partial(now)

    async def _on_silence(self) -> None:
        if not self._speech_active:
            return
        self._silence_frames += 1
        if self._silence_frames < self._silence_required:
            return
        await self._emit_segment()
        self._reset_segment_state()

    async def _emit_segment(self) -> None:
        if not self._buffer:
            return
        ended_at = time.time()
        duration_ms = (ended_at - self._segment_started) * 1000
        if duration_ms < self._min_duration:
            logger.debug(
                "Discarding short segment (%.0f ms < %.0f ms)",
                duration_ms,
                self._min_duration,
            )
            return
        audio = bytes(self._buffer)
        text, confidence, language = await self._transcribe_async(audio)
        if not text:
            logger.debug("Discarding empty transcription result")
            return
        if not self._language_allowed(language):
            await self._emit_skipped(
                reason="non_english_final",
                language=language,
                text_length=len(text),
            )
            return
        payload: Dict[str, Any] = {
            "segment": self._segment_index,
            "text": text,
            "confidence": confidence,
            "language": language,
            "started_at": self._segment_started,
            "ended_at": ended_at,
            "duration_ms": duration_ms,
        }
        await self._publish_event("asr_final", payload)
        await self._emit_telemetry_final(
            duration_ms=duration_ms,
            confidence=confidence,
            language=language,
            text=text,
        )
        timestamp = time.strftime("%H:%M:%S", time.localtime(ended_at))
        conf_display = f"{confidence:.2f}" if isinstance(confidence, float) else "n/a"
        lang_display = language or "und"
        print(f"[{timestamp}] ({lang_display}, conf={conf_display}) {text}", flush=True)

    async def _emit_partial(self, timestamp: float) -> None:
        audio = bytes(self._buffer)
        text, confidence, language = await self._transcribe_async(audio)
        if not text:
            return
        if not self._language_allowed(language):
            await self._emit_skipped(
                reason="non_english_partial",
                language=language,
                text_length=len(text),
            )
            self._last_partial_at = timestamp
            self._last_partial_text = text
            return
        if text == self._last_partial_text:
            return
        self._last_partial_text = text
        self._last_partial_at = timestamp
        latency_ms = (timestamp - self._segment_started) * 1000
        payload: Dict[str, Any] = {
            "segment": self._segment_index,
            "text": text,
            "confidence": confidence,
            "language": language,
            "started_at": self._segment_started,
            "ended_at": timestamp,
            "latency_ms": latency_ms,
        }
        await self._publish_event("asr_partial", payload)
        await self._emit_telemetry_partial(
            latency_ms=latency_ms,
            text=text,
            confidence=confidence,
            language=language,
        )

    async def _emit_skipped(
        self, *, reason: str, language: Optional[str], text_length: int
    ) -> None:
        if self._telemetry is None:
            return
        try:
            await self._telemetry.segment_skipped(
                segment=self._segment_index,
                reason=reason,
                language=language,
                text_length=text_length,
            )
        except Exception:  # pragma: no cover - telemetry guard
            logger.debug("Telemetry segment_skipped failed", exc_info=True)

    async def _transcribe_async(self, audio: bytes) -> tuple[str, Optional[float], Optional[str]]:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self._transcriber.transcribe, audio)
        return result.text, result.confidence, result.language

    def _language_allowed(self, language: Optional[str]) -> bool:
        if self._allow_non_english:
            return True
        if not language:
            return True
        normalized = language.lower()
        return normalized.startswith("en")

    async def _publish_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        if self._orchestrator is None:
            return
        try:
            await self._orchestrator.publish(event_type, payload)
        except Exception:  # pragma: no cover - network guard
            logger.warning("Failed to publish %s to orchestrator", event_type, exc_info=True)

    async def _emit_telemetry_partial(
        self,
        *,
        latency_ms: float,
        text: str,
        confidence: Optional[float],
        language: Optional[str],
    ) -> None:
        if self._telemetry is None:
            return
        try:
            await self._telemetry.segment_partial(
                segment=self._segment_index,
                latency_ms=latency_ms,
                text=text,
                confidence=confidence,
                language=language,
            )
        except Exception:  # pragma: no cover - telemetry guard
            logger.debug("Telemetry segment_partial failed", exc_info=True)

    async def _emit_telemetry_final(
        self,
        *,
        duration_ms: float,
        confidence: Optional[float],
        language: Optional[str],
        text: str,
    ) -> None:
        if self._telemetry is None:
            return
        try:
            await self._telemetry.segment_final(
                segment=self._segment_index,
                duration_ms=duration_ms,
                confidence=confidence,
                language=language,
                text=text,
            )
        except Exception:  # pragma: no cover - telemetry guard
            logger.debug("Telemetry segment_final failed", exc_info=True)

    def _is_silence(self, frame: bytes) -> bool:
        if self._vad is not None and getattr(
            self._vad, "supports_silence_detection", True
        ):
            try:
                return not bool(self._vad.is_speech(frame))
            except Exception:  # pragma: no cover - defensive guard
                logger.debug("VAD check failed; falling back to energy threshold", exc_info=True)
        if not frame:
            return True
        mv = memoryview(frame).cast("h")
        energy = sum(sample * sample for sample in mv) / max(1, len(mv))
        return energy < self._energy_threshold

    async def _flush_active_segment(self) -> None:
        if not self._speech_active:
            return
        if self._buffer:
            await self._emit_segment()
        self._reset_segment_state()

    def _reset_segment_state(self) -> None:
        self._buffer.clear()
        self._speech_active = False
        self._silence_frames = 0
        self._last_partial_text = ""
        self._last_partial_at = 0.0


__all__ = ["SimpleASRPipeline"]
