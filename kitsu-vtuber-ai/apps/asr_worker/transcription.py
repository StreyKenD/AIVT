from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Protocol, Sequence, cast

from types import SimpleNamespace

from .config import ASRConfig, SherpaConfig
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
    backend = (config.backend or "whisper").strip().lower()
    if backend == "whisper":
        return _build_faster_whisper_transcriber(config)
    if backend == "sherpa":
        return _build_sherpa_transcriber(config)
    raise ValueError(f"Unsupported ASR backend: {config.backend}")


def _build_faster_whisper_transcriber(config: ASRConfig) -> Transcriber:
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


def _build_sherpa_transcriber(config: ASRConfig) -> Transcriber:
    sherpa_module = load_module_if_available("sherpa_onnx")
    if sherpa_module is None:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "sherpa-onnx is not installed. Install it to use the 'sherpa' ASR backend."
        )
    numpy_module_obj = load_module_if_available("numpy")
    if numpy_module_obj is None:  # pragma: no cover - dependency guard
        raise RuntimeError("numpy is required for the Sherpa-ONNX backend")
    numpy_module = cast(NumpyModule, numpy_module_obj)
    recognizer = _create_sherpa_recognizer(sherpa_module, config.sherpa)
    logger.info("ASR transcriber initialised (backend=sherpa, provider=%s)", config.sherpa.provider)
    return SherpaOnnxTranscriber(recognizer, config.sample_rate, numpy_module)


def _create_sherpa_recognizer(module: object, sherpa_cfg: SherpaConfig) -> object:
    OfflineRecognizer = getattr(module, "OfflineRecognizer", None)
    if OfflineRecognizer is None:  # pragma: no cover - dependency guard
        raise RuntimeError("sherpa_onnx.OfflineRecognizer is unavailable")

    if sherpa_cfg.config_file:
        config_cls = getattr(module, "OfflineRecognizerConfig", None)
        if config_cls is None or not hasattr(config_cls, "from_yaml"):  # pragma: no cover - dependency guard
            raise RuntimeError(
                "The installed sherpa_onnx version does not support loading from YAML configs."
            )
        cfg = config_cls.from_yaml(sherpa_cfg.config_file)
        return OfflineRecognizer(cfg)

    missing = [
        name
        for name, value in [
            ("tokens", sherpa_cfg.tokens),
            ("encoder", sherpa_cfg.encoder),
            ("decoder", sherpa_cfg.decoder),
            ("joiner", sherpa_cfg.joiner),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"Sherpa backend requires the following paths in the config: {', '.join(missing)}."
        )

    if hasattr(OfflineRecognizer, "from_files"):
        return OfflineRecognizer.from_files(
            tokens=sherpa_cfg.tokens,
            encoder=sherpa_cfg.encoder,
            decoder=sherpa_cfg.decoder,
            joiner=sherpa_cfg.joiner,
            num_threads=sherpa_cfg.num_threads,
            provider=sherpa_cfg.provider,
            model_type=sherpa_cfg.model_type,
            decoding_method=sherpa_cfg.decoding_method,
        )

    # Fallback: try direct constructor signature (older versions).  # pragma: no cover - legacy guard
    return OfflineRecognizer(
        tokens=sherpa_cfg.tokens,
        encoder=sherpa_cfg.encoder,
        decoder=sherpa_cfg.decoder,
        joiner=sherpa_cfg.joiner,
        num_threads=sherpa_cfg.num_threads,
        provider=sherpa_cfg.provider,
        model_type=sherpa_cfg.model_type,
        decoding_method=sherpa_cfg.decoding_method,
    )


class SherpaOnnxTranscriber:
    def __init__(self, recognizer: object, sample_rate: int, numpy_module: NumpyModule) -> None:
        self._recognizer = recognizer
        self._sample_rate = sample_rate
        self._np = numpy_module

    def _create_stream(self) -> object:
        create_stream = getattr(self._recognizer, "create_stream", None)
        if create_stream is None:  # pragma: no cover - dependency guard
            raise RuntimeError("sherpa recognizer does not expose create_stream()")
        return create_stream()

    def _decode_stream(self, stream: object) -> None:
        decode_stream = getattr(self._recognizer, "decode_stream", None)
        if decode_stream is None:  # pragma: no cover - dependency guard
            raise RuntimeError("sherpa recognizer does not expose decode_stream()")
        decode_stream(stream)

    def _cleanup_stream(self, stream: object) -> None:
        free_stream = getattr(self._recognizer, "free_stream", None)
        if callable(free_stream):
            free_stream(stream)

    def transcribe(self, audio: bytes) -> TranscriptionResult:
        if not audio:
            return TranscriptionResult(text="", confidence=None, language=None)
        np_module = self._np
        samples = (
            np_module.frombuffer(audio, dtype=np_module.int16).astype(np_module.float32)
            / 32768.0
        )
        stream = self._create_stream()
        accept_waveform = getattr(stream, "accept_waveform", None)
        if not callable(accept_waveform):  # pragma: no cover - dependency guard
            raise RuntimeError("sherpa stream does not expose accept_waveform()")
        accept_waveform(self._sample_rate, samples)
        self._decode_stream(stream)
        result = getattr(stream, "result", SimpleNamespace(text=""))
        text = getattr(result, "text", "") or ""
        self._cleanup_stream(stream)
        return TranscriptionResult(text=text.strip(), confidence=None, language=None)


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
    "SherpaOnnxTranscriber",
    "NumpyArray",
    "NumpyModule",
    "SegmentLike",
    "Transcriber",
    "TranscriptionResult",
    "WhisperModelLike",
    "build_transcriber",
]
