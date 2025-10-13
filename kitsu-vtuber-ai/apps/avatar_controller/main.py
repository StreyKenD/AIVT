from __future__ import annotations

# VTube Studio integration module.

import asyncio
import json
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Protocol

from libs.common import configure_json_logging

try:  # pragma: no cover - optional dependency for CI environments
    import websockets
except ImportError:  # pragma: no cover - offline smoke mode
    websockets = None  # type: ignore


configure_json_logging("avatar_controller")
logger = logging.getLogger("kitsu.avatar")

WebSocketFactory = Callable[[str], Awaitable["WebSocketLike"]]


class WebSocketLike(Protocol):  # type: ignore[name-defined]
    async def send(self, data: str) -> None:
        ...

    async def recv(self) -> str:
        ...

    async def close(self) -> None:
        ...


@dataclass(slots=True)
class AvatarState:
    expression: str = "smile"
    mouth: str = "closed"

    def to_dict(self) -> Dict[str, str]:
        return {"expression": self.expression, "mouth": self.mouth}


class VTubeStudioClient:
    """Minimal VTube Studio WebSocket client with auth + expression helpers."""

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        auth_token: Optional[str] = None,
        websocket_factory: Optional[WebSocketFactory] = None,
    ) -> None:
        self._url = url or os.getenv("VTS_URL", "ws://127.0.0.1:8001")
        self._auth_token = auth_token or os.getenv("VTS_AUTH_TOKEN")
        self._plugin_name = os.getenv("VTS_PLUGIN_NAME", "Kitsu.exe Controller")
        self._developer = os.getenv("VTS_DEVELOPER", "Kitsu.exe")
        self._factory = websocket_factory
        self._ws: Optional[WebSocketLike] = None
        self._lock = asyncio.Lock()
        self._connected = False
        self.state = AvatarState()
        self._viseme_map = {
            "sil": "MouthClosed",
            "a": "MouthSmall",
            "e": "MouthSmile",
            "i": "MouthWide",
            "o": "MouthRound",
            "u": "MouthRound",
        }

    async def connect(self) -> None:
        async with self._lock:
            if self._connected:
                return
            if websockets is None and self._factory is None:
                logger.warning("websockets not installed; running VTS client in dry mode")
                self._connected = True
                return
            factory = self._factory or websockets.connect  # type: ignore[union-attr]
            self._ws = await factory(self._url)
            await self._authenticate()
            self._connected = True
            logger.info("Connected to VTube Studio at %s", self._url)

    async def _authenticate(self) -> None:
        if self._ws is None:
            return
        handshake = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": secrets.token_hex(8),
            "messageType": "AuthenticationRequest",
            "data": {
                "pluginName": self._plugin_name,
                "developer": self._developer,
                "authenticationToken": self._auth_token,
            },
        }
        await self._ws.send(json.dumps(handshake))
        try:
            response = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
            logger.debug("VTS handshake response: %s", response)
        except asyncio.TimeoutError:  # pragma: no cover - runtime guard
            logger.warning("No handshake acknowledgement received from VTS")

    async def ensure_connected(self) -> None:
        if self._connected:
            return
        await self.connect()

    async def close(self) -> None:
        async with self._lock:
            if self._ws is not None:
                await self._ws.close()
                self._ws = None
            self._connected = False

    async def set_expression(self, expression: str, intensity: float = 0.6) -> None:
        await self.ensure_connected()
        self.state.expression = expression
        payload = {
            "messageType": "ExpressionActivationRequest",
            "data": {
                "expressionFile": expression,
                "expressionID": expression,
                "weight": max(0.0, min(1.0, intensity)),
                "mode": "set",
            },
            "requestID": secrets.token_hex(4),
        }
        await self._send(payload)

    async def set_viseme(self, phoneme: str) -> None:
        await self.ensure_connected()
        viseme = self._viseme_map.get(phoneme.lower(), "MouthClosed")
        self.state.mouth = viseme
        payload = {
            "messageType": "HotkeyTriggerRequest",
            "data": {"hotkeyID": viseme},
            "requestID": secrets.token_hex(4),
        }
        await self._send(payload)

    async def trigger_action(self, action: str) -> None:
        await self.ensure_connected()
        payload = {
            "messageType": "HotkeyTriggerRequest",
            "data": {"hotkeyID": action},
            "requestID": secrets.token_hex(4),
        }
        await self._send(payload)

    async def _send(self, payload: Dict[str, Any]) -> None:
        if self._ws is None:
            logger.debug("VTS send skipped (dry mode): %s", payload)
            return
        try:
            await self._ws.send(json.dumps(payload))
        except Exception as exc:  # pragma: no cover - runtime guard
            logger.warning("VTS send failed: %s", exc)
            self._connected = False


async def run_controller() -> None:
    client = VTubeStudioClient()
    gestures = ["smile", "angry", "blush", "sweat", "heart"]
    while True:
        for gesture in gestures:
            await client.set_expression(gesture)
            await asyncio.sleep(1.0)
        await asyncio.sleep(5.0)


def main() -> None:
    logger.info("Avatar controller starting")
    try:
        asyncio.run(run_controller())
    except KeyboardInterrupt:  # pragma: no cover
        logger.info("Avatar controller stopped")


if __name__ == "__main__":
    main()
