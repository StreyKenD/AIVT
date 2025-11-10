from __future__ import annotations

import asyncio

from libs.common import configure_json_logging

from .logger import LOGGER_NAME, logger
from .runner import run

configure_json_logging(LOGGER_NAME)


async def main() -> None:
    await run()


def run_once() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:  # pragma: no cover - manual stop
        logger.info("ASR worker interrupted")
    except Exception:
        logger.exception("ASR worker terminated with an unexpected error")
        raise


if __name__ == "__main__":
    run_once()
