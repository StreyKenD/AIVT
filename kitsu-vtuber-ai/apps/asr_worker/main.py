from __future__ import annotations

import asyncio
import time

from libs.common import configure_json_logging

from .logger import LOGGER_NAME, logger
from .runner import run

configure_json_logging(LOGGER_NAME)


async def main() -> None:
    await run()


def run_forever() -> None:
    delay = 1.0
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:  # pragma: no cover - manual stop
            logger.info("ASR worker interrupted")
            break
        except Exception as exc:  # pragma: no cover - top-level guard
            logger.exception("ASR worker crashed: %s", exc)
        else:
            logger.warning(
                "ASR worker main loop exited unexpectedly; restarting in %.1fs", delay
            )
        time.sleep(delay)
        delay = min(delay * 2, 30.0)


if __name__ == "__main__":
    run_forever()
