from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

try:
    from obsws_python import obsws
except ImportError:  # pragma: no cover - optional dependency for offline mode
    obsws = None  # type: ignore

logger = logging.getLogger("kitsu.obs")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


class OBSController:
    def __init__(self) -> None:
        self.host = os.getenv("OBS_HOST", "localhost")
        self.port = int(os.getenv("OBS_PORT", "4455"))
        self.password = os.getenv("OBS_PASSWORD", "")
        self._client: Optional[obsws] = None

    async def connect(self) -> None:
        if obsws is None:
            logger.warning("obsws-python not installed; running in dry mode")
            return
        logger.info("Connecting to OBS at %s:%s", self.host, self.port)
        self._client = obsws(self.host, self.port, self.password)
        self._client.connect()

    async def set_scene(self, scene: str) -> None:
        logger.info("Switching OBS scene to %s", scene)
        if self._client is None:
            return
        self._client.call("SetCurrentProgramScene", {"sceneName": scene})

    async def toggle_overlay(self, enabled: bool) -> None:
        logger.info("Toggling overlay enabled=%s", enabled)


async def run_controller() -> None:
    controller = OBSController()
    await controller.connect()
    scenes = ["Intro", "Just Chatting", "Gameplay"]
    idx = 0
    while True:
        await controller.set_scene(scenes[idx % len(scenes)])
        idx += 1
        await asyncio.sleep(4.0)


def main() -> None:
    logger.info("OBS controller starting")
    try:
        asyncio.run(run_controller())
    except KeyboardInterrupt:  # pragma: no cover
        logger.info("OBS controller stopped")


if __name__ == "__main__":
    main()
