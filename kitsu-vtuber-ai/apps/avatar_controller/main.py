from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Dict

logger = logging.getLogger("kitsu.avatar")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


@dataclass
class AvatarState:
    expression: str = "smile"
    mouth: str = "closed"

    def to_dict(self) -> Dict[str, str]:
        return {"expression": self.expression, "mouth": self.mouth}


class VTubeStudioClient:
    def __init__(self) -> None:
        self.state = AvatarState()

    async def set_expression(self, expression: str, intensity: float = 0.6) -> None:
        logger.info("[VTS] set_expression=%s intensity=%.2f", expression, intensity)
        self.state.expression = expression

    async def set_mouth(self, viseme: str) -> None:
        logger.info("[VTS] set_mouth=%s", viseme)
        self.state.mouth = viseme

    async def trigger_action(self, action: str) -> None:
        logger.info("[VTS] trigger_action=%s", action)


async def run_controller() -> None:
    client = VTubeStudioClient()
    gestures = ["smile", "angry", "blush", "sweat", "heart"]
    while True:
        for gesture in gestures:
            await client.set_expression(gesture)
            await asyncio.sleep(1.0)
        await asyncio.sleep(5.0)


def main() -> None:
    logger.info("Avatar controller starting in stub mode")
    try:
        asyncio.run(run_controller())
    except KeyboardInterrupt:  # pragma: no cover
        logger.info("Avatar controller stopped")


if __name__ == "__main__":
    main()
