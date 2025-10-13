import asyncio
import json
from typing import List

import pytest

from apps.avatar_controller.main import VTubeStudioClient


class DummyWebSocket:
    def __init__(self) -> None:
        self.sent: List[str] = []
        self.closed = False

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self) -> str:
        return json.dumps({"status": "ok"})

    async def close(self) -> None:
        self.closed = True


def test_vts_client_handshake_and_actions() -> None:
    async def _scenario() -> None:
        socket = DummyWebSocket()

        async def factory(url: str) -> DummyWebSocket:
            assert url == "ws://fake"
            return socket

        client = VTubeStudioClient(
            url="ws://fake", auth_token="token-123", websocket_factory=factory
        )
        await client.connect()

        await client.set_expression("Smile", intensity=0.75)
        await client.set_viseme("a")
        await client.trigger_action("Wave")

        assert any("AuthenticationRequest" in payload for payload in socket.sent)
        expression_payload = json.loads(socket.sent[-3])
        assert expression_payload["data"]["expressionID"] == "Smile"

        viseme_payload = json.loads(socket.sent[-2])
        assert viseme_payload["data"]["hotkeyID"] == "MouthSmall"

        action_payload = json.loads(socket.sent[-1])
        assert action_payload["data"]["hotkeyID"] == "Wave"

        await client.close()
        assert socket.closed is True

    asyncio.run(_scenario())
