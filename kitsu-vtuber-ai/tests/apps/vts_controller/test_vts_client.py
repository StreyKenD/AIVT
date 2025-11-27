import asyncio
import json

import pytest

from apps.avatar_controller.main import VTubeStudioClient


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.recv_queue: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False

    async def send(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def recv(self) -> str:
        return await self.recv_queue.get()

    async def close(self) -> None:
        self.closed = True


async def _factory_with_socket(ws: FakeWebSocket, url: str) -> FakeWebSocket:
    assert url.startswith("ws://")
    return ws


@pytest.mark.asyncio()
async def test_set_expression_sends_activation_payload() -> None:
    ws = FakeWebSocket()
    ws.recv_queue.put_nowait(json.dumps({"status": "ok"}))

    async def factory(url: str) -> FakeWebSocket:
        return await _factory_with_socket(ws, url)

    client = VTubeStudioClient(websocket_factory=factory)
    await client.set_expression("smile", 0.8)

    assert client.state.expression == "smile"
    expression_payload = ws.sent[-1]
    assert expression_payload["messageType"] == "ExpressionActivationRequest"
    assert expression_payload["data"]["expressionFile"] == "smile"
    assert expression_payload["data"]["weight"] == pytest.approx(0.8)


@pytest.mark.asyncio()
async def test_set_viseme_maps_phoneme_to_hotkey() -> None:
    ws = FakeWebSocket()
    ws.recv_queue.put_nowait(json.dumps({"status": "ok"}))

    async def factory(url: str) -> FakeWebSocket:
        return await _factory_with_socket(ws, url)

    client = VTubeStudioClient(websocket_factory=factory)
    await client.set_viseme("a")

    assert client.state.mouth == "MouthSmall"
    payload = ws.sent[-1]
    assert payload["messageType"] == "HotkeyTriggerRequest"
    assert payload["data"]["hotkeyID"] == "MouthSmall"
