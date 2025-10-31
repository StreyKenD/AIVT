from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Protocol

import numpy as np

from libs.config import (
    BarkTTSSettings,
    CoquiTTSSettings,
    PiperTTSSettings,
    TTSSettings,
    XTTSSettings,
)
from libs.telemetry import TelemetryClient

logger = logging.getLogger("kitsu.tts")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


@dataclass
class TTSResult:
    audio_path: Path
    visemes: List[Dict[str, float]]
    voice: str
    latency_ms: float
    cached: bool
    backend: str


@dataclass
class TTSJob:
    text: str
    voice: Optional[str]
    request_id: str
    future: asyncio.Future[TTSResult]
    backend: Optional[str] = field(default=None, init=False)


class Synthesizer(Protocol):
    async def synthesize(
        self, text: str, voice: Optional[str], destination: Path
    ) -> Path:
        """Generate audio at the destination path and return the file path."""

    def describe_voice(self, requested_voice: Optional[str]) -> Optional[str]:
        """Return a human-friendly voice identifier for telemetry/cache."""


class TTSDiskCache:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _key(self, text: str, voice: Optional[str]) -> str:
        digest = hashlib.sha1()
        digest.update(text.encode("utf-8"))
        digest.update((voice or "default").encode("utf-8"))
        return digest.hexdigest()

    def resolve(self, text: str, voice: Optional[str]) -> tuple[Path, Path]:
        key = self._key(text, voice)
        return self._root / f"{key}.wav", self._root / f"{key}.json"

    def get(self, text: str, voice: Optional[str]) -> Optional[TTSResult]:
        audio_path, meta_path = self.resolve(text, voice)
        if not audio_path.exists() or not meta_path.exists():
            return None
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            visemes = metadata.get("visemes", [])
            latency_ms = float(metadata.get("latency_ms", 0.0))
            voice_id = metadata.get("voice", voice or "default")
            backend = metadata.get("backend", "unknown")
            return TTSResult(
                audio_path=audio_path,
                visemes=[
                    {"time": float(item["time"]), "rms": float(item["rms"])}
                    for item in visemes
                ],
                voice=voice_id,
                latency_ms=latency_ms,
                cached=True,
                backend=str(backend),
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("Failed to read TTS cache %s: %s", meta_path, exc)
            return None

    def store(self, text: str, voice: Optional[str], result: TTSResult) -> None:
        audio_path, meta_path = self.resolve(text, voice)
        if result.audio_path != audio_path:
            audio_path.write_bytes(result.audio_path.read_bytes())
            result.audio_path = audio_path
        payload = {
            "voice": result.voice,
            "latency_ms": result.latency_ms,
            "visemes": result.visemes,
            "backend": result.backend,
        }
        meta_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


class CoquiSynthesizer:
    def __init__(self, config: CoquiTTSSettings) -> None:
        self._config = config
        module = self._load_module()
        try:
            self._tts = module.TTS(
                model_name=config.model_name,
                progress_bar=False,
            )
        except Exception as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                f"Failed to load Coqui TTS model '{config.model_name}': {exc}"
            ) from exc

    @staticmethod
    def _load_module():
        try:
            from TTS.api import TTS as CoquiTTS  # type: ignore
        except Exception as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "Coqui TTS is not installed. Install it with 'poetry install' or 'pip install TTS'."
            ) from exc
        return type("Module", (), {"TTS": CoquiTTS})

    def _resolve_speaker(self, voice: Optional[str]) -> Optional[str]:
        if voice:
            mapped = self._config.speaker_map.get(voice, voice)
            return mapped.strip() or None
        if self._config.default_speaker:
            return self._config.default_speaker.strip() or None
        return None

    def describe_voice(self, requested_voice: Optional[str]) -> Optional[str]:
        if requested_voice:
            return requested_voice
        if self._config.default_speaker:
            return self._config.default_speaker
        return self._config.model_name

    async def synthesize(
        self, text: str, voice: Optional[str], destination: Path
    ) -> Path:
        speaker = self._resolve_speaker(voice)
        loop = asyncio.get_running_loop()

        def _run() -> None:
            kwargs: Dict[str, object] = {"text": text, "file_path": destination}
            if speaker:
                kwargs["speaker"] = speaker
            self._tts.tts_to_file(**kwargs)

        await loop.run_in_executor(None, _run)
        return destination


class PiperSynthesizer:
    def __init__(self, config: PiperTTSSettings) -> None:
        self._config = config
        raw_model = (config.model or "").strip()
        raw_binary = (config.binary or "").strip()
        if not raw_model:
            raise RuntimeError("PIPER_MODEL is not configured")
        if not raw_binary:
            raise RuntimeError("PIPER_PATH is not configured")
        self._binary = Path(raw_binary).expanduser()
        self._model = Path(raw_model).expanduser()
        raw_config = (config.config or "").strip()
        self._config_path: Path | None = (
            Path(raw_config).expanduser() if raw_config else None
        )

    def _resolve_speaker(self, voice: Optional[str]) -> Optional[str]:
        if voice:
            mapped = self._config.speaker_map.get(voice, voice)
            return mapped.strip() or None
        if self._config.default_speaker:
            return self._config.default_speaker.strip() or None
        return None

    def describe_voice(self, requested_voice: Optional[str]) -> Optional[str]:
        if requested_voice:
            return requested_voice
        if self._config.default_speaker:
            return self._config.default_speaker
        return "piper"

    async def synthesize(
        self, text: str, voice: Optional[str], destination: Path
    ) -> Path:
        cmd = [
            str(self._binary),
            "--model",
            str(self._model),
            "--output_file",
            str(destination),
        ]
        if self._config_path is not None:
            cmd.extend(["--config", str(self._config_path)])
        speaker = self._resolve_speaker(voice)
        if speaker:
            cmd.extend(["--speaker", speaker])
        logger.info("Running Piper TTS via %s", cmd)
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdin is not None
        process.stdin.write(text.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                f"Piper failed: {stderr.decode('utf-8', errors='ignore')}"
            )
        if stdout:
            logger.debug("Piper stdout: %s", stdout[:120])
        return destination


class BarkSynthesizer:
    def __init__(self, config: BarkTTSSettings) -> None:
        self._config = config
        module = self._load_module()
        self._generate_audio = module["generate_audio"]
        self._preload_models = module["preload_models"]
        self._sample_rate = module["sample_rate"]
        self._models_ready = False

    @staticmethod
    def _load_module():
        try:
            from bark import SAMPLE_RATE, generate_audio, preload_models  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                "Bark is not installed. Install it with 'pip install bark-voice-clone'."
            ) from exc
        return {
            "generate_audio": generate_audio,
            "preload_models": preload_models,
            "sample_rate": SAMPLE_RATE,
        }

    def _resolve_prompt(self, voice: Optional[str]) -> Optional[str]:
        if voice:
            prompt = self._config.speaker_prompts.get(voice, voice)
            if prompt:
                return prompt
        if self._config.history_prompt:
            return self._config.history_prompt
        return self._config.voice_preset

    def describe_voice(self, requested_voice: Optional[str]) -> Optional[str]:
        if requested_voice:
            return requested_voice
        if self._config.history_prompt:
            return self._config.history_prompt
        return self._config.voice_preset

    async def synthesize(
        self, text: str, voice: Optional[str], destination: Path
    ) -> Path:
        loop = asyncio.get_running_loop()
        prompt = self._resolve_prompt(voice)
        text_temp = self._config.text_temperature
        waveform_temp = self._config.waveform_temperature

        def _run() -> np.ndarray:
            if not self._models_ready:
                self._preload_models()
                self._models_ready = True
            audio_array = self._generate_audio(
                text,
                history_prompt=prompt,
                text_temp=text_temp,
                waveform_temp=waveform_temp,
            )
            return np.array(audio_array, dtype=np.float32)

        audio = await loop.run_in_executor(None, _run)
        if audio.ndim > 1:
            audio = audio.flatten()
        audio = np.clip(audio, -1.0, 1.0)
        int_audio = (audio * 32767).astype("<i2")
        with wave.open(str(destination), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self._sample_rate)
            wav_file.writeframes(int_audio.tobytes())
        return destination


class XTTSSynthesizer:
    def __init__(self, config: XTTSSettings) -> None:
        self._config = config
        module = CoquiSynthesizer._load_module()
        try:
            self._tts = module.TTS(
                model_name=config.model_name,
                progress_bar=False,
            )
        except Exception as exc:  # pragma: no cover - dependency guard
            raise RuntimeError(
                f"Failed to load XTTS model '{config.model_name}': {exc}"
            ) from exc

    def _resolve_speaker_path(self, voice: Optional[str]) -> Optional[Path]:
        if voice:
            mapped = self._config.speaker_wavs.get(voice)
            candidate = Path(mapped or voice).expanduser()
            if candidate.exists():
                return candidate
        if self._config.default_speaker_wav:
            candidate = Path(self._config.default_speaker_wav).expanduser()
            if candidate.exists():
                return candidate
        return None

    def _resolve_language(self, voice: Optional[str]) -> str:
        if voice and voice in self._config.language_overrides:
            return self._config.language_overrides[voice]
        return self._config.default_language

    def describe_voice(self, requested_voice: Optional[str]) -> Optional[str]:
        if requested_voice:
            if requested_voice in self._config.speaker_wavs:
                return requested_voice
            candidate = Path(requested_voice)
            if candidate.exists():
                return candidate.stem
            return requested_voice
        if self._config.default_speaker_name:
            return self._config.default_speaker_name
        if self._config.default_speaker_wav:
            return Path(self._config.default_speaker_wav).stem
        return "xtts"

    async def synthesize(
        self, text: str, voice: Optional[str], destination: Path
    ) -> Path:
        loop = asyncio.get_running_loop()
        speaker_path = self._resolve_speaker_path(voice)
        if speaker_path is None:
            raise RuntimeError(
                "XTTS requires a speaker WAV. Configure 'tts.xtts.default_speaker_wav' or provide a voice mapped to a file."
            )
        language = self._resolve_language(voice)

        def _run() -> None:
            self._tts.tts_to_file(
                text=text,
                speaker_wav=str(speaker_path),
                language=language,
                file_path=destination,
            )

        await loop.run_in_executor(None, _run)
        return destination


class SilentSynthesizer:
    """Deterministic fallback used in test environments."""

    def describe_voice(self, requested_voice: Optional[str]) -> Optional[str]:
        if requested_voice:
            return requested_voice
        return "synthetic"

    async def synthesize(
        self, text: str, voice: Optional[str], destination: Path
    ) -> Path:
        duration = max(1.0, min(6.0, len(text) / 15))
        sample_rate = 22050
        total_frames = int(sample_rate * duration)
        silence_frame = (0).to_bytes(2, "little", signed=True)
        with wave.open(str(destination), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(silence_frame * total_frames)
        return destination


def _build_synthesizers(config: TTSSettings) -> List[Synthesizer]:
    order: List[str]
    if config.backend == "auto":
        order = ["coqui", "xtts", "bark", "piper"]
    else:
        order = [config.backend]
    for fallback in config.fallback_backends:
        if fallback not in order:
            order.append(fallback)
    synthesizers: List[Synthesizer] = []
    seen: set[str] = set()
    for backend in order:
        name = backend.strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            if name == "coqui":
                synthesizers.append(CoquiSynthesizer(config.coqui))
            elif name == "piper":
                synthesizers.append(PiperSynthesizer(config.piper))
            elif name == "bark":
                synthesizers.append(BarkSynthesizer(config.bark))
            elif name == "xtts":
                synthesizers.append(XTTSSynthesizer(config.xtts))
            elif name == "silent":
                synthesizers.append(SilentSynthesizer())
            else:
                logger.warning("Unknown TTS backend configured: %s", backend)
        except Exception as exc:
            logger.warning("Skipping TTS backend %s: %s", backend, exc)
    synthesizers.append(SilentSynthesizer())
    return synthesizers


class TelemetryPublisher(Protocol):
    async def publish(self, event_type: str, payload: Dict[str, object]) -> None:
        """Emit a structured telemetry event."""


class TTSService:
    def __init__(
        self,
        *,
        config: TTSSettings,
        telemetry: Optional[TelemetryPublisher] = None,
        cache_dir: str | Path | None = None,
    ) -> None:
        output_root = cache_dir or config.cache_dir
        output_dir = Path(output_root)
        self._config = config
        self._cache = TTSDiskCache(output_dir)
        self._synthesizers = _build_synthesizers(config)
        self._queue: asyncio.Queue[TTSJob] = asyncio.Queue()
        self._current_job: Optional[TTSJob] = None
        self._cancel_event = asyncio.Event()
        self._telemetry = telemetry or TelemetryClient.from_env(source="tts_worker")
        real_backends = [
            s for s in self._synthesizers if not isinstance(s, SilentSynthesizer)
        ]
        logger.info(
            "TTS initialized with backends=%s (cache_dir=%s)",
            [s.__class__.__name__ for s in real_backends] or ["silent"],
            output_dir,
        )

    async def enqueue(
        self, text: str, voice: Optional[str] = None, request_id: Optional[str] = None
    ) -> TTSResult:
        loop = asyncio.get_running_loop()
        future: "asyncio.Future[TTSResult]" = loop.create_future()
        job = TTSJob(
            text=text,
            voice=voice,
            request_id=request_id or hashlib.sha1(text.encode("utf-8")).hexdigest(),
            future=future,
        )
        await self._queue.put(job)
        return await future

    async def cancel_active(self) -> None:
        if self._current_job is None:
            return
        logger.info("Cancelling TTS job in progress: %s", self._current_job.request_id)
        self._cancel_event.set()

    async def worker(self) -> None:
        logger.info("TTS queue ready (%d synthesizers)", len(self._synthesizers))
        while True:
            job = await self._queue.get()
            logger.debug(
                "Processing TTS job request_id=%s text_len=%d voice=%s queue_depth=%d",
                job.request_id,
                len(job.text),
                job.voice,
                self._queue.qsize(),
            )
            cached = self._cache.get(job.text, job.voice)
            if cached:
                logger.info(
                    "TTS cache hit request_id=%s voice=%s latency_ms=%.2f backend=%s",
                    job.request_id,
                    cached.voice,
                    cached.latency_ms,
                    cached.backend,
                )
                job.backend = cached.backend
                job.future.set_result(cached)
                await self._emit_metric(job, cached, cached=True)
                self._queue.task_done()
                continue
            self._cancel_event.clear()
            self._current_job = job
            start = time.perf_counter()
            try:
                result = await self._synthesize(job)
                result.latency_ms = round((time.perf_counter() - start) * 1000, 2)
                self._cache.store(job.text, job.voice, result)
                job.future.set_result(result)
                await self._emit_metric(job, result, cached=False)
            except asyncio.CancelledError as exc:
                logger.info("TTS job cancelled: %s", job.request_id)
                job.future.set_exception(exc)
                await self._emit_metric(job, None, cached=False, error=str(exc))
            except Exception as exc:
                logger.exception("Failed to generate TTS: %s", exc)
                job.future.set_exception(exc)
                await self._emit_metric(job, None, cached=False, error=str(exc))
            finally:
                self._current_job = None
                self._queue.task_done()

    async def _emit_metric(
        self,
        job: TTSJob,
        result: Optional[TTSResult],
        *,
        cached: bool,
        error: Optional[str] = None,
    ) -> None:
        if self._telemetry is None:
            return
        payload: Dict[str, object] = {
            "request_id": job.request_id,
            "text_length": len(job.text),
            "voice": job.voice or (result.voice if result else None),
            "cached": cached,
            "queue_depth": self._queue.qsize(),
            "backend": job.backend or (result.backend if result else None),
        }
        if result is not None:
            payload["latency_ms"] = result.latency_ms
        if error is None:
            payload["status"] = "ok"
        else:
            payload["status"] = "error"
            payload["error"] = error
        try:
            await self._telemetry.publish("tts.completed", payload)
        except Exception as exc:  # pragma: no cover - telemetry guard
            logger.warning("Failed to send TTS metric: %s", exc)

    async def _synthesize(self, job: TTSJob) -> TTSResult:
        audio_path, _ = self._cache.resolve(job.text, job.voice)
        last_error: Optional[str] = None
        for synthesizer in self._synthesizers:
            if self._cancel_event.is_set():
                raise asyncio.CancelledError()
            backend_name = synthesizer.__class__.__name__.lower()
            job.backend = backend_name
            try:
                path = await synthesizer.synthesize(job.text, job.voice, audio_path)
                visemes = self._viseme_from_text(job.text)
                voice_id = self._describe_voice(synthesizer, job.voice)
                logger.info(
                    "TTS generated request_id=%s voice=%s backend=%s",
                    job.request_id,
                    voice_id,
                    backend_name,
                )
                return TTSResult(
                    audio_path=path,
                    visemes=visemes,
                    voice=voice_id,
                    latency_ms=0.0,
                    cached=False,
                    backend=backend_name,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = str(exc)
                logger.warning(
                    "Synthesizer %s failed: %s", synthesizer.__class__.__name__, exc
                )
                continue
        raise RuntimeError(
            last_error or "No synthesizer was able to generate audio"
        )

    @staticmethod
    def _describe_voice(synthesizer: Synthesizer, requested_voice: Optional[str]) -> str:
        descriptor = getattr(synthesizer, "describe_voice", None)
        if callable(descriptor):
            resolved = descriptor(requested_voice)
            if resolved:
                return resolved
        if requested_voice:
            return requested_voice
        return synthesizer.__class__.__name__.lower()

    @staticmethod
    def _viseme_from_text(text: str) -> List[Dict[str, float]]:
        clean = text.strip()
        if not clean:
            return [{"time": 0.0, "rms": 0.25}]
        step = max(0.05, 0.6 / max(len(clean), 1))
        time_cursor = 0.0
        visemes: List[Dict[str, float]] = []
        vowels = set("aeiou")
        for char in clean.lower():
            energy = 0.4
            if char in vowels:
                energy = 0.8
            elif char.isalpha():
                energy = 0.6
            elif char.isspace():
                energy = 0.2
            visemes.append(
                {"time": round(time_cursor, 2), "rms": round(min(1.0, energy), 2)}
            )
            time_cursor += step
        return visemes


_service: Optional[TTSService] = None


def get_tts_service(
    *,
    config: TTSSettings,
    telemetry: Optional[TelemetryPublisher] = None,
    cache_dir: str | Path | None = None,
) -> TTSService:
    global _service
    if _service is None:
        _service = TTSService(config=config, telemetry=telemetry, cache_dir=cache_dir)
    return _service


__all__ = [
    "TTSService",
    "TTSResult",
    "get_tts_service",
    "PiperSynthesizer",
    "CoquiSynthesizer",
    "BarkSynthesizer",
    "XTTSSynthesizer",
    "SilentSynthesizer",
]
