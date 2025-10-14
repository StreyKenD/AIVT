from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol

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


@dataclass
class TTSJob:
    text: str
    voice: Optional[str]
    request_id: str
    future: asyncio.Future[TTSResult]


class Synthesizer(Protocol):
    async def synthesize(
        self, text: str, voice: Optional[str], destination: Path
    ) -> Path:
        """Generate audio at the destination path and return the file path."""


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
            return TTSResult(
                audio_path=audio_path,
                visemes=[
                    {"time": float(item["time"]), "rms": float(item["rms"])}
                    for item in visemes
                ],
                voice=voice_id,
                latency_ms=latency_ms,
                cached=True,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("Falha ao ler cache TTS %s: %s", meta_path, exc)
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
        }
        meta_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )


class CoquiSynthesizer:
    def __init__(self) -> None:
        module = self._load_module()
        self._tts = module.TTS(
            model_name=os.getenv("TTS_MODEL_NAME", "tts_models/en/vctk/vits")
        )
        self._device = os.getenv("TTS_DEVICE", "cuda")

    @staticmethod
    def _load_module():
        try:
            from TTS.api import TTS as CoquiTTS  # type: ignore
        except Exception as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("Coqui TTS não está instalado") from exc
        return type("Module", (), {"TTS": CoquiTTS})

    async def synthesize(
        self, text: str, voice: Optional[str], destination: Path
    ) -> Path:
        loop = asyncio.get_running_loop()

        def _run() -> None:
            kwargs = {"file_path": destination}
            if voice:
                kwargs["speaker"] = voice
            self._tts.tts_to_file(text, **kwargs)

        await loop.run_in_executor(None, _run)
        return destination


class PiperSynthesizer:
    def __init__(self) -> None:
        self._binary = Path(os.getenv("PIPER_PATH", "piper"))
        self._model = Path(os.getenv("PIPER_MODEL", ""))
        self._config = Path(os.getenv("PIPER_CONFIG", ""))
        if not self._model:
            raise RuntimeError("PIPER_MODEL não configurado")
        if not self._binary:
            raise RuntimeError("PIPER_PATH não configurado")

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
        if self._config:
            cmd.extend(["--config", str(self._config)])
        logger.info("Executando Piper TTS via %s", cmd)
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
                f"Piper falhou: {stderr.decode('utf-8', errors='ignore')}"
            )
        if stdout:
            logger.debug("Piper stdout: %s", stdout[:120])
        return destination


class SilentSynthesizer:
    """Fallback determinístico usado em ambientes de teste."""

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


def _default_synthesizers() -> List[Synthesizer]:
    synthesizers: List[Synthesizer] = []
    if os.getenv("TTS_DISABLE_COQUI") != "1":
        try:
            synthesizers.append(CoquiSynthesizer())
        except Exception as exc:
            logger.warning("Coqui indisponível: %s", exc)
    if os.getenv("TTS_DISABLE_PIPER") != "1":
        try:
            synthesizers.append(PiperSynthesizer())
        except Exception as exc:
            logger.warning("Piper indisponível: %s", exc)
    synthesizers.append(SilentSynthesizer())
    return synthesizers


class TelemetryPublisher(Protocol):
    async def publish(self, event_type: str, payload: Dict[str, object]) -> None:
        """Emit a structured telemetry event."""


class TTSService:
    def __init__(self, telemetry: Optional[TelemetryPublisher] = None) -> None:
        output_dir = Path(os.getenv("TTS_OUTPUT_DIR", "artifacts/tts"))
        self._cache = TTSDiskCache(output_dir)
        self._synthesizers = _default_synthesizers()
        self._queue: asyncio.Queue[TTSJob] = asyncio.Queue()
        self._current_job: Optional[TTSJob] = None
        self._cancel_event = asyncio.Event()
        self._telemetry = telemetry or TelemetryClient.from_env(service="tts_worker")

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
        logger.info("Cancelando job TTS em andamento: %s", self._current_job.request_id)
        self._cancel_event.set()

    async def worker(self) -> None:
        logger.info("Fila TTS pronta (%d synthesizers)", len(self._synthesizers))
        while True:
            job = await self._queue.get()
            cached = self._cache.get(job.text, job.voice)
            if cached:
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
                logger.info("Job TTS cancelado: %s", job.request_id)
                job.future.set_exception(exc)
                await self._emit_metric(job, None, cached=False, error=str(exc))
            except Exception as exc:
                logger.exception("Falha ao gerar TTS: %s", exc)
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
            logger.debug("Falha ao enviar métrica TTS: %s", exc)

    async def _synthesize(self, job: TTSJob) -> TTSResult:
        audio_path, _ = self._cache.resolve(job.text, job.voice)
        for synthesizer in self._synthesizers:
            if self._cancel_event.is_set():
                raise asyncio.CancelledError()
            try:
                path = await synthesizer.synthesize(job.text, job.voice, audio_path)
                visemes = self._viseme_from_text(job.text)
                voice_id = job.voice or self._detect_voice_name(synthesizer)
                return TTSResult(
                    audio_path=path,
                    visemes=visemes,
                    voice=voice_id,
                    latency_ms=0.0,
                    cached=False,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Synthesizer %s falhou: %s", synthesizer.__class__.__name__, exc
                )
                continue
        raise RuntimeError("Nenhum sintetizador conseguiu gerar áudio")

    @staticmethod
    def _detect_voice_name(synthesizer: Synthesizer) -> str:
        if isinstance(synthesizer, CoquiSynthesizer):
            return os.getenv("TTS_MODEL_NAME", "coqui")
        if isinstance(synthesizer, PiperSynthesizer):
            return "piper"
        return "synthetic"

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


def get_tts_service() -> TTSService:
    global _service
    if _service is None:
        _service = TTSService()
    return _service


__all__ = [
    "TTSService",
    "TTSResult",
    "get_tts_service",
]
