from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import AsyncIterator

try:
    import webrtcvad
except ImportError:  # pragma: no cover - optional dependency for offline tests
    webrtcvad = None  # type: ignore


logger = logging.getLogger("kitsu.asr")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


async def microphone_stream() -> AsyncIterator[bytes]:
    """Yield silent audio chunks to emulate microphone capture."""
    frame = b"\x00" * 640
    while True:
        await asyncio.sleep(0.3)
        yield frame


async def vad_detects_speech(frame: bytes, sample_rate: int = 16000) -> bool:
    if webrtcvad is None:
        return random.random() > 0.6
    voice = webrtcvad.Vad(1)
    return voice.is_speech(frame, sample_rate)


async def emit_transcriptions() -> None:
    phrases = [
        "Hello chat!", "Ara ara~", "Kitsu warming up", "Switching persona", "Hydrate reminder!",
    ]
    async for frame in microphone_stream():
        has_speech = await vad_detects_speech(frame)
        if not has_speech:
            continue
        transcript = random.choice(phrases)
        logger.info("[ASR] partial=%s", transcript)
        await asyncio.sleep(0.2)


async def main() -> None:
    logger.info("Starting ASR worker (simulated mode)")
    try:
        await emit_transcriptions()
    except asyncio.CancelledError:  # pragma: no cover - graceful shutdown
        logger.info("ASR worker cancelled")


if __name__ == "__main__":
    asyncio.run(main())
