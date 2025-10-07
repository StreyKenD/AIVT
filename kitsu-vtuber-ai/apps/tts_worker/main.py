from __future__ import annotations

import asyncio
import logging
import os

from .service import TTSService, get_tts_service

logger = logging.getLogger("kitsu.tts")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


async def _bootstrap_jobs(service: TTSService) -> None:
    await asyncio.sleep(1.0)
    await service.enqueue("Hello world", voice=None)


async def main() -> None:
    service = get_tts_service()
    logger.info("Booting TTS worker loop")
    await asyncio.gather(service.worker(), _bootstrap_jobs(service))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:  # pragma: no cover
        logger.info("TTS worker interrupted")
