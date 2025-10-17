from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Protocol, Sequence, cast

from .config import ASRConfig
from .logger import logger
from .utils import load_module_if_available


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    confidence: Optional[float]
    language: Optional[str]


class Transcriber(Protocol):
    def transcribe(self, audio: bytes) -> TranscriptionResult:
        """Return the transcription for the given PCM16 audio payload."""


class NumpyArray(Protocol):
    def astype(self, dtype: object) -> "NumpyArray":
        ...

    def __truediv__(self, other: float) -> "NumpyArray":
        ...


class NumpyModule(Protocol):
    int16: object
    float32: object

    def frombuffer(self, buffer: bytes, dtype: object) -> NumpyArray:
        ...


class SegmentLike(Protocol):
    text: str
    avg_logprob: float | None


class WhisperModelLike(Protocol):
    def transcribe(
        self,
        audio: NumpyArray,
        *,
        beam_size: int,
        language: str,
        condition_on_previous_text: bool,
        vad_filter: bool,
        without_timestamps: bool,
    ) -> tuple[Iterable[SegmentLike], object | None]:
        ...


def build_transcriber(config: ASRConfig) -> Transcriber:
    faster_whisper = load_module_if_available("faster_whisper")
    if faster_whisper is None:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "faster-whisper is required for the ASR worker. Install the optional dependency."
        )

    WhisperModel = getattr(faster_whisper, "WhisperModel")
    numpy_module_obj = load_module_if_available("numpy")
    if numpy_module_obj is None:  # pragma: no cover - dependency guard
        raise RuntimeError("numpy is required alongside faster-whisper")
    numpy_module = cast(NumpyModule, numpy_module_obj)

    compute_type = config.compute_type or (
        "int8_float16" if config.device_preference == "cuda" else "int8"
    )
    device_candidates = [config.device_preference]
    if config.device_preference != "cpu":
        device_candidates.append("cpu")

    last_error: Optional[Exception] = None
    for device in device_candidates:
        try:
            compute_for_device = compute_type if device != "cpu" else "int8"
            model = cast(
                WhisperModelLike,
                WhisperModel(  # type: ignore[call-arg]
                    config.model_name,
                    device=device,
                    compute_type=compute_for_device,
                ),
            )
            if device == "cpu" and config.device_preference != "cpu":
                logger.warning(
                    "ASR worker falling back to CPU execution for faster-whisper."
                )
            logger.info(
                "ASR transcriber initialised (model=%s device=%s compute_type=%s)",
                config.model_name,
                device,
                compute_for_device,
            )
            return FasterWhisperTranscriber(model, config.sample_rate, numpy_module)
        except Exception as exc:  # pragma: no cover - hardware guard
            last_error = exc
            logger.warning("Failed to initialise faster-whisper on %s: %s", device, exc)
            continue
    raise RuntimeError("Unable to initialise faster-whisper") from last_error


class FasterWhisperTranscriber:
    def __init__(
        self, model: WhisperModelLike, sample_rate: int, numpy_module: NumpyModule
    ) -> None:
        self._model = model
        self._sample_rate = sample_rate
        self._np = numpy_module

    def transcribe(self, audio: bytes) -> TranscriptionResult:
        if not audio:
            return TranscriptionResult(text="", confidence=None, language=None)
        np_module = self._np
        audio_array = (
            np_module.frombuffer(audio, dtype=np_module.int16).astype(np_module.float32)
            / 32768.0
        )
        segments_iter, info = self._model.transcribe(
            audio_array,
            beam_size=1,
            language="en",
            condition_on_previous_text=False,
            vad_filter=False,
            without_timestamps=True,
        )
        segments = list(segments_iter)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        confidence = _confidence_from_segments(segments)
        language = getattr(info, "language", None) if info else None
        return TranscriptionResult(text=text, confidence=confidence, language=language)


def _confidence_from_segments(segments: Sequence[SegmentLike]) -> Optional[float]:
    if not segments:
        return None
    scores = []
    for segment in segments:
        value = segment.avg_logprob
        if value is None:
            continue
        scores.append(float(value))
    if not scores:
        return None
    mean_score = sum(scores) / len(scores)
    score = math.exp(min(0.0, mean_score))
    return float(max(0.0, min(1.0, score)))


__all__ = [
    "FasterWhisperTranscriber",
    "NumpyArray",
    "NumpyModule",
    "SegmentLike",
    "Transcriber",
    "TranscriptionResult",
    "WhisperModelLike",
    "build_transcriber",
]
