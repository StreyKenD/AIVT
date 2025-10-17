from __future__ import annotations

import asyncio
import contextlib
from typing import AsyncIterator, Optional

from .config import ASRConfig
from .logger import logger

try:  # pragma: no cover - optional dependency guard
    import sounddevice as sd
except ImportError:  # pragma: no cover - handled at runtime
    sd = None  # type: ignore[assignment]


class MicrophoneStream:
    """Captures audio frames from the default microphone using sounddevice."""

    def __init__(self, config: ASRConfig) -> None:
        if sd is None:
            raise RuntimeError(
                "sounddevice is required for ASR. Install it or set ASR_FAKE_AUDIO=1."
            )
        self._config = config
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)
        self._stream: Optional[sd.RawInputStream] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def __aenter__(self) -> "MicrophoneStream":
        self._loop = asyncio.get_running_loop()
        self._stream = sd.RawInputStream(
            samplerate=self._config.sample_rate,
            blocksize=self._config.frame_samples,
            channels=1,
            dtype="int16",
            device=self._config.input_device,
            callback=self._on_frame,
        )
        self._stream.start()
        logger.info(
            "Mic stream started (device=%s sample_rate=%s frame_ms=%s)",
            self._config.input_device,
            self._config.sample_rate,
            self._config.frame_duration_ms,
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._stream is not None:
            with contextlib.suppress(Exception):
                self._stream.stop()
                self._stream.close()
        while not self._queue.empty():
            self._queue.get_nowait()
        self._stream = None
        self._loop = None

    def _on_frame(self, indata, frames, time_info, status) -> None:  # pragma: no cover
        if status:
            logger.debug("sounddevice status: %s", status)
        if self._loop is None:
            return
        data = bytes(indata)
        self._loop.call_soon_threadsafe(self._enqueue, data)

    def _enqueue(self, data: bytes) -> None:
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._queue.put_nowait(data)

    async def frames(self) -> AsyncIterator[bytes]:
        while True:
            frame = await self._queue.get()
            yield frame


__all__ = ["MicrophoneStream"]
