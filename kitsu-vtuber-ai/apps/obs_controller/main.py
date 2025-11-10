from __future__ import annotations

import asyncio
import functools
import logging
import os
from typing import Any, Callable, Optional, TypeVar
from urllib.parse import urlparse

from libs.common import configure_json_logging

try:  # pragma: no cover - optional dependency when running unit tests
    from obsws_python import obsws
except ImportError:  # pragma: no cover - offline/dev environments
    obsws = None  # type: ignore


configure_json_logging("obs_controller")
logger = logging.getLogger("kitsu.obs")

T = TypeVar("T")


class OBSController:
    """Reconnect-friendly wrapper around the obs-websocket client."""

    def __init__(self) -> None:
        default_host = os.getenv("OBS_HOST", "127.0.0.1")
        default_port = int(os.getenv("OBS_PORT", "4455"))
        url = os.getenv("OBS_WS_URL")
        if url:
            parsed = urlparse(url)
            self.host = parsed.hostname or default_host
            self.port = parsed.port or default_port
        else:
            self.host = default_host
            self.port = default_port

        self.password = os.getenv("OBS_WS_PASSWORD", os.getenv("OBS_PASSWORD", ""))
        self.ws_url = url or f"ws://{self.host}:{self.port}"
        self._client: Optional[obsws] = None
        self._lock = asyncio.Lock()
        self._connected = asyncio.Event()

    async def _run_blocking(
        self, func: Callable[..., T], *args: Any, **kwargs: Any
    ) -> T:
        loop = asyncio.get_running_loop()
        bound = functools.partial(func, *args, **kwargs)
        return await loop.run_in_executor(None, bound)

    async def connect(self) -> None:
        if obsws is None:
            logger.warning("obsws-python not installed; running in dry mode")
            self._connected.set()
            return
        backoff = 1.0
        while True:
            try:
                logger.info("Connecting to OBS at %s", self.ws_url)
                client = obsws(self.host, self.port, self.password)
                await self._run_blocking(client.connect)
                self._client = client
                self._connected.set()
                logger.info("OBS connection established")
                return
            except asyncio.CancelledError:
                self._connected.clear()
                raise
            except Exception as exc:  # pragma: no cover - runtime guard
                self._connected.clear()
                logger.warning(
                    "OBS connection failed: %s (retrying in %.1fs)", exc, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def ensure_connected(self) -> None:
        if self._connected.is_set():
            return
        async with self._lock:
            if self._connected.is_set():
                return
            await self.connect()

    async def set_scene(self, scene: str) -> None:
        await self.ensure_connected()
        logger.info("Switching OBS scene to %s", scene)
        if self._client is None:
            return
        try:
            await self._run_blocking(
                self._client.call, "SetCurrentProgramScene", {"sceneName": scene}
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.warning("OBS scene switch failed: %s", exc)
            self._connected.clear()

    async def toggle_filter(self, source: str, filter_name: str, enabled: bool) -> None:
        await self.ensure_connected()
        if self._client is None:
            return
        logger.info(
            "Toggling OBS filter %s on %s -> %s",
            filter_name,
            source,
            "on" if enabled else "off",
        )
        try:
            await self._run_blocking(
                self._client.call,
                "SetSourceFilterEnabled",
                {
                    "sourceName": source,
                    "filterName": filter_name,
                    "filterEnabled": enabled,
                },
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.warning("Failed to toggle filter: %s", exc)
            self._connected.clear()

    async def panic(self) -> None:
        logger.warning("OBS panic macro triggered")
        await self.toggle_filter(
            "Microphone", os.getenv("OBS_PANIC_FILTER", "HardMute"), True
        )


async def run_controller() -> None:
    controller = OBSController()
    await controller.ensure_connected()
    scenes = os.getenv("OBS_SCENES", "Intro,Just Chatting,Gameplay").split(",")
    idx = 0
    while True:
        await controller.set_scene(scenes[idx % len(scenes)].strip())
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
