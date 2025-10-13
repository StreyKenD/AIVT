from __future__ import annotations

import asyncio
import logging
import os

from libs.common import configure_json_logging

from .service import TTSService, get_tts_service

configure_json_logging("tts_worker")
logger = logging.getLogger("kitsu.tts")


async def _bootstrap_jobs(service: TTSService) -> None:
    await asyncio.sleep(1.0)
    result = await service.enqueue("Hello world", voice=None)
    logger.info(
        "Job de teste concluído voice=%s cached=%s latency=%.2fms",
        result.voice,
        result.cached,
        result.latency_ms,
    )


async def main() -> None:
    service = get_tts_service()
    logger.info("Booting TTS worker loop")
    await asyncio.gather(service.worker(), _bootstrap_jobs(service))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:  # pragma: no cover
        logger.info("TTS worker interrupted")
