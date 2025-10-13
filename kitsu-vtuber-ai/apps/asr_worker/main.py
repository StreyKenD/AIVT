from __future__ import annotations

import asyncio
import contextlib
import importlib
import importlib.util
import logging
import math
import os
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable, Dict, List, Optional, Protocol

import httpx

from libs.common import configure_json_logging

configure_json_logging("asr_worker")
logger = logging.getLogger("kitsu.asr")


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    confidence: Optional[float]
    language: Optional[str]


class Transcriber(Protocol):
    def transcribe(self, audio: bytes) -> TranscriptionResult:
        """Return the transcription for the given PCM16 audio payload."""


class VoiceActivityDetector(Protocol):
    def is_speech(self, frame: bytes) -> bool:
        """Return True if the frame contains speech."""


class AudioSource(Protocol):
    async def frames(self) -> AsyncIterator[bytes]:
        """Yield PCM16 audio frames of a fixed duration."""


class OrchestratorClient:
    """Publishes ASR events to the orchestrator's broker via HTTP."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    async def publish(self, event_type: str, payload: Dict[str, object]) -> None:
        data = {"type": event_type, **payload}
        try:
            await self._client.post(f"{self._base_url}/events/asr", json=data)
        except Exception as exc:  # pragma: no cover - network guard
            logger.warning("Failed to publish %s: %s", event_type, exc, exc_info=True)

    async def aclose(self) -> None:
        await self._client.aclose()


@dataclass
class ASRConfig:
    model_name: str
    orchestrator_url: str
    sample_rate: int
    frame_duration_ms: int
    partial_interval_ms: int
    silence_duration_ms: int
    vad_mode: str
    vad_aggressiveness: int
    input_device: Optional[str]
    fake_audio: bool
    device_preference: str
    compute_type: Optional[str]

    @property
    def frame_samples(self) -> int:
        return int(self.sample_rate * self.frame_duration_ms / 1000)

    @property
    def frame_bytes(self) -> int:
        return self.frame_samples * 2

    @property
    def partial_interval(self) -> float:
        return max(0.05, self.partial_interval_ms / 1000)

    @property
    def silence_threshold_frames(self) -> int:
        minimum_ms = max(self.silence_duration_ms, self.frame_duration_ms)
        return max(1, int(math.ceil(minimum_ms / self.frame_duration_ms)))


def load_module_if_available(name: str) -> Optional[object]:
    spec = importlib.util.find_spec(name)
    if spec is None:
        return None
    module = importlib.import_module(name)
    return module


def build_transcriber(config: ASRConfig) -> Transcriber:
    faster_whisper = load_module_if_available("faster_whisper")
    if faster_whisper is None:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "faster-whisper is required for the ASR worker. Install the optional dependency."
        )

    WhisperModel = getattr(faster_whisper, "WhisperModel")
    numpy_module = load_module_if_available("numpy")
    if numpy_module is None:  # pragma: no cover - dependency guard
        raise RuntimeError("numpy is required alongside faster-whisper")

    compute_type = config.compute_type or ("int8_float16" if config.device_preference == "cuda" else "int8")
    device_candidates = [config.device_preference]
    if config.device_preference != "cpu":
        device_candidates.append("cpu")

    last_error: Optional[Exception] = None
    for device in device_candidates:
        try:
            model = WhisperModel(  # type: ignore[call-arg]
                config.model_name,
                device=device,
                compute_type=compute_type if device != "cpu" else "int8",
            )
            if device == "cpu" and config.device_preference != "cpu":
                logger.warning(
                    "ASR worker falling back to CPU execution for faster-whisper."
                )
            return FasterWhisperTranscriber(model, config.sample_rate, numpy_module)
        except Exception as exc:  # pragma: no cover - hardware guard
            last_error = exc
            logger.warning("Failed to initialise faster-whisper on %s: %s", device, exc)
            continue
    raise RuntimeError("Unable to initialise faster-whisper") from last_error


class FasterWhisperTranscriber:
    def __init__(self, model: object, sample_rate: int, numpy_module: object) -> None:
        self._model = model
        self._sample_rate = sample_rate
        self._np = numpy_module

    def transcribe(self, audio: bytes) -> TranscriptionResult:
        if not audio:
            return TranscriptionResult(text="", confidence=None, language=None)
        np_module = self._np
        audio_array = np_module.frombuffer(audio, dtype=np_module.int16).astype(np_module.float32) / 32768.0
        segments_iter, info = self._model.transcribe(  # type: ignore[attr-defined]
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


def _confidence_from_segments(segments: list[object]) -> Optional[float]:
    if not segments:
        return None
    scores = []
    for segment in segments:
        value = getattr(segment, "avg_logprob", None)
        if value is None:
            continue
        scores.append(float(value))
    if not scores:
        return None
    mean_score = sum(scores) / len(scores)
    score = math.exp(min(0.0, mean_score))
    return float(max(0.0, min(1.0, score)))


def build_vad(config: ASRConfig) -> VoiceActivityDetector:
    if config.vad_mode.lower() == "none":
        return PassthroughVAD(config.frame_bytes)
    if config.vad_mode.lower() != "webrtc":
        raise RuntimeError(f"Unsupported VAD mode: {config.vad_mode}")
    vad_module = load_module_if_available("webrtcvad")
    if vad_module is None:
        raise RuntimeError("webrtcvad is not installed; set ASR_VAD=none to proceed")
    VadCls = getattr(vad_module, "Vad")
    vad = VadCls(config.vad_aggressiveness)
    return WebRtcVAD(vad, config.frame_bytes, config.sample_rate)


class PassthroughVAD:
    def __init__(self, frame_bytes: int) -> None:
        self._frame_bytes = frame_bytes

    def is_speech(self, frame: bytes) -> bool:
        if len(frame) != self._frame_bytes:
            raise ValueError("Unexpected frame size for VAD passthrough")
        return True


class WebRtcVAD:
    def __init__(self, vad: object, frame_bytes: int, sample_rate: int) -> None:
        self._vad = vad
        self._frame_bytes = frame_bytes
        self._sample_rate = sample_rate

    def is_speech(self, frame: bytes) -> bool:
        if len(frame) != self._frame_bytes:
            raise ValueError("Frame size mismatch for WebRTC VAD")
        return bool(self._vad.is_speech(frame, self._sample_rate))


class FakeAudioSource:
    """Generates silence for smoke tests or when no device is available."""

    def __init__(self, frame_bytes: int, interval: float) -> None:
        self._frame_bytes = frame_bytes
        self._interval = interval
        self._running = True

    async def frames(self) -> AsyncIterator[bytes]:
        blank = b"\x00" * self._frame_bytes
        while self._running:
            await asyncio.sleep(self._interval)
            yield blank


class SoundDeviceAudioSource:
    def __init__(self, config: ASRConfig) -> None:
        self._config = config
        self._module = load_module_if_available("sounddevice")
        if self._module is None:
            raise RuntimeError("sounddevice is not installed")
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
        self._stream = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stream = self._module.RawInputStream(
            samplerate=self._config.sample_rate,
            blocksize=self._config.frame_samples,
            channels=1,
            dtype="int16",
            device=self._config.input_device,
            callback=self._on_frame,
        )
        self._stream.start()

    async def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def _on_frame(self, indata, frames, _time, status) -> None:  # pragma: no cover - external callback
        if status:
            logger.debug("sounddevice status: %s", status)
        data = bytes(indata)
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._enqueue, data)

    def _enqueue(self, data: bytes) -> None:
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            try:
                self._queue.put_nowait(data)
            except asyncio.QueueFull:
                logger.debug("Dropped audio frame due to full queue")

    async def frames(self) -> AsyncIterator[bytes]:
        while True:
            frame = await self._queue.get()
            yield frame


class PyAudioSource:
    def __init__(self, config: ASRConfig) -> None:
        self._config = config
        self._module = load_module_if_available("pyaudio")
        if self._module is None:
            raise RuntimeError("pyaudio is not installed")
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
        self._stream = None
        self._pa = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._worker: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._pa = self._module.PyAudio()
        self._stream = self._pa.open(
            format=self._module.paInt16,
            channels=1,
            rate=self._config.sample_rate,
            input=True,
            frames_per_buffer=self._config.frame_samples,
            input_device_index=self._config.input_device,
        )
        self._worker = asyncio.create_task(self._reader())

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        if self._pa is not None:
            self._pa.terminate()
            self._pa = None

    async def _reader(self) -> None:  # pragma: no cover - hardware guard
        assert self._stream is not None
        while True:
            data = await asyncio.get_running_loop().run_in_executor(
                None,
                self._stream.read,
                self._config.frame_samples,
            )
            try:
                self._queue.put_nowait(data)
            except asyncio.QueueFull:
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    self._queue.put_nowait(data)
                except asyncio.QueueFull:
                    logger.debug("Dropped PyAudio frame due to full queue")

    async def frames(self) -> AsyncIterator[bytes]:
        while True:
            frame = await self._queue.get()
            yield frame


class SpeechPipeline:
    def __init__(
        self,
        *,
        config: ASRConfig,
        vad: VoiceActivityDetector,
        transcriber: Transcriber,
        orchestrator: OrchestratorClient,
    ) -> None:
        self._config = config
        self._vad = vad
        self._transcriber = transcriber
        self._orchestrator = orchestrator
        self._speech_active = False
        self._buffer = bytearray()
        self._silence_frames = 0
        self._segment_started_at = 0.0
        self._last_partial_at = 0.0
        self._last_partial_text = ""
        self._segment_counter = 0

    async def process(self, frames: AsyncIterator[bytes]) -> None:
        try:
            async for frame in frames:
                await self._handle_frame(frame)
        except asyncio.CancelledError:
            raise

    async def _handle_frame(self, frame: bytes) -> None:
        if len(frame) != self._config.frame_bytes:
            logger.debug("Adjusting frame size mismatch: got %d bytes", len(frame))
            frame = frame[: self._config.frame_bytes]
            if len(frame) < self._config.frame_bytes:
                frame = frame.ljust(self._config.frame_bytes, b"\x00")
        if self._vad.is_speech(frame):
            await self._on_speech(frame)
        else:
            await self._on_silence()

    async def _on_speech(self, frame: bytes) -> None:
        if not self._speech_active:
            self._speech_active = True
            self._buffer.clear()
            self._segment_started_at = time.time()
            self._last_partial_at = 0.0
            self._last_partial_text = ""
            self._segment_counter += 1
            logger.debug("Speech segment %s started", self._segment_counter)
        self._buffer.extend(frame)
        self._silence_frames = 0
        now = time.time()
        if now - self._segment_started_at < 0.1:
            return
        if self._last_partial_at and now - self._last_partial_at < self._config.partial_interval:
            return
        await self._emit_partial(now)

    async def _on_silence(self) -> None:
        if not self._speech_active:
            return
        self._silence_frames += 1
        if self._silence_frames < self._config.silence_threshold_frames:
            return
        ended_at = time.time()
        await self._emit_final(ended_at)
        self._speech_active = False
        self._buffer.clear()
        self._silence_frames = 0

    async def _emit_partial(self, timestamp: float) -> None:
        text, confidence, language = await self._transcribe_async()
        if not text or text == self._last_partial_text:
            return
        self._last_partial_text = text
        self._last_partial_at = timestamp
        latency_ms = (timestamp - self._segment_started_at) * 1000
        payload = {
            "segment": self._segment_counter,
            "text": text,
            "confidence": confidence,
            "language": language,
            "started_at": self._segment_started_at,
            "ended_at": timestamp,
            "latency_ms": latency_ms,
        }
        logger.info("[ASR] partial (%.0f ms): %s", latency_ms, text)
        await self._orchestrator.publish("asr_partial", payload)

    async def _emit_final(self, timestamp: float) -> None:
        text, confidence, language = await self._transcribe_async()
        if not text:
            logger.debug("Discarding empty final segment")
            return
        duration_ms = (len(self._buffer) / 2 / self._config.sample_rate) * 1000
        payload = {
            "segment": self._segment_counter,
            "text": text,
            "confidence": confidence,
            "language": language,
            "started_at": self._segment_started_at,
            "ended_at": timestamp,
            "duration_ms": duration_ms,
        }
        logger.info(
            "[ASR] final (%.0f ms, conf=%s): %s",
            duration_ms,
            f"{confidence:.2f}" if confidence is not None else "n/a",
            text,
        )
        await self._orchestrator.publish("asr_final", payload)

    async def _transcribe_async(self) -> tuple[str, Optional[float], Optional[str]]:
        loop = asyncio.get_running_loop()
        audio = bytes(self._buffer)
        result = await loop.run_in_executor(None, self._transcriber.transcribe, audio)
        return result.text, result.confidence, result.language


def load_config() -> ASRConfig:
    orchestrator_url = os.getenv("ORCHESTRATOR_URL")
    if not orchestrator_url:
        host = os.getenv("ORCH_HOST", "127.0.0.1")
        port = int(os.getenv("ORCH_PORT", "8000"))
        orchestrator_url = f"http://{host}:{port}"
    model_name = os.getenv("ASR_MODEL", "small.en")
    sample_rate = int(os.getenv("ASR_SAMPLE_RATE", "16000"))
    frame_duration_ms = int(os.getenv("ASR_FRAME_MS", "20"))
    partial_interval_ms = int(os.getenv("ASR_PARTIAL_INTERVAL_MS", "200"))
    silence_duration_ms = int(os.getenv("ASR_SILENCE_MS", "500"))
    vad_mode = os.getenv("ASR_VAD", "webrtc")
    vad_aggressiveness = int(os.getenv("ASR_VAD_AGGRESSIVENESS", "2"))
    input_device = os.getenv("ASR_INPUT_DEVICE")
    fake_audio = os.getenv("ASR_FAKE_AUDIO", "0").lower() in {"1", "true", "yes"}
    device_preference = os.getenv("ASR_DEVICE", "cuda")
    compute_type = os.getenv("ASR_COMPUTE_TYPE")
    return ASRConfig(
        model_name=model_name,
        orchestrator_url=orchestrator_url,
        sample_rate=sample_rate,
        frame_duration_ms=frame_duration_ms,
        partial_interval_ms=partial_interval_ms,
        silence_duration_ms=silence_duration_ms,
        vad_mode=vad_mode,
        vad_aggressiveness=vad_aggressiveness,
        input_device=input_device,
        fake_audio=fake_audio,
        device_preference=device_preference,
        compute_type=compute_type,
    )


async def main() -> None:
    config = load_config()
    orchestrator = OrchestratorClient(config.orchestrator_url)
    try:
        vad = build_vad(config)
        transcriber = build_transcriber(config)
        pipeline = SpeechPipeline(
            config=config,
            vad=vad,
            transcriber=transcriber,
            orchestrator=orchestrator,
        )
        logger.info(
            "Starting ASR worker with model=%s, sample_rate=%s Hz, frame=%sms",
            config.model_name,
            config.sample_rate,
            config.frame_duration_ms,
        )
        async with acquire_audio_source(config) as audio_source:
            await pipeline.process(audio_source.frames())
    except asyncio.CancelledError:  # pragma: no cover - shutdown flow
        raise
    except Exception as exc:  # pragma: no cover - startup guard
        logger.exception("ASR worker failed: %s", exc)
    finally:
        await orchestrator.aclose()


@contextlib.asynccontextmanager
async def acquire_audio_source(config: ASRConfig) -> AsyncIterator[AudioSource]:
    frame_interval = config.frame_duration_ms / 1000
    if config.fake_audio:
        logger.warning("ASR worker using synthetic audio source (silence mode)")
        source = FakeAudioSource(config.frame_bytes, frame_interval)
        try:
            yield source
        finally:
            source._running = False
        return

    factories: List[tuple[str, Callable[[ASRConfig], object]]] = [
        ("sounddevice", SoundDeviceAudioSource),
        ("pyaudio", PyAudioSource),
    ]

    for name, factory in factories:
        try:
            backend = factory(config)
        except RuntimeError as exc:
            logger.debug("Audio backend %s unavailable: %s", name, exc)
            continue
        try:
            await backend.start()
            logger.info("ASR worker capturando áudio com %s", name)

            try:
                yield backend
            finally:
                await backend.stop()
            return
        except Exception as exc:  # pragma: no cover - device guard
            logger.warning("Falha ao iniciar captura com %s: %s", name, exc, exc_info=True)
            with contextlib.suppress(Exception):
                await backend.stop()

    logger.warning("Nenhum backend de áudio disponível; usando modo sintético")
    fallback = FakeAudioSource(config.frame_bytes, frame_interval)
    try:
        yield fallback
    finally:
        fallback._running = False


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:  # pragma: no cover - manual stop
        logger.info("ASR worker interrupted")
