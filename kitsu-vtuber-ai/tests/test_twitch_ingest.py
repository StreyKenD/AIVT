from typing import List, Optional, Tuple

import asyncio

import pytest

from apps.twitch_ingest.main import ChatMessage, TwitchCommandRouter


class FakeBridge:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, Tuple, dict]] = []

    async def toggle_tts(self, enabled: bool) -> None:
        self.calls.append(("toggle_tts", (enabled,), {}))

    async def set_scene(self, scene: str) -> None:
        self.calls.append(("set_scene", (scene,), {}))

    async def update_persona(
        self,
        *,
        style: Optional[str],
        chaos: Optional[float],
        energy: Optional[float],
    ) -> None:
        self.calls.append(
            ("update_persona", (), {"style": style, "chaos": chaos, "energy": energy})
        )

    async def emit_chat(self, role: str, text: str) -> None:
        self.calls.append(("emit_chat", (role, text), {}))


def test_router_dispatches_commands() -> None:
    async def _scenario() -> None:
        bridge = FakeBridge()
        router = TwitchCommandRouter(bridge, cooldown_seconds=0.0)

        await router.handle(ChatMessage(author="viewer", content="!mute"))
        await router.handle(ChatMessage(author="viewer", content="!unmute"))
        await router.handle(ChatMessage(author="viewer", content="!scene Gameplay"))
        await router.handle(ChatMessage(author="viewer", content="!style kawaii 20 80"))

        assert bridge.calls[0] == ("toggle_tts", (False,), {})
        assert bridge.calls[1] == ("toggle_tts", (True,), {})
        assert bridge.calls[2] == ("set_scene", ("Gameplay",), {})
        assert bridge.calls[3][0] == "update_persona"
        assert bridge.calls[3][2]["style"] == "kawaii"
        assert bridge.calls[3][2]["chaos"] == pytest.approx(0.2)
        assert bridge.calls[3][2]["energy"] == pytest.approx(0.8)

    asyncio.run(_scenario())


def test_router_forwards_chat() -> None:
    async def _scenario() -> None:
        bridge = FakeBridge()
        router = TwitchCommandRouter(bridge, cooldown_seconds=0.0)

        await router.handle(ChatMessage(author="viewer", content="Hello there!"))

        assert bridge.calls == [("emit_chat", ("user", "Hello there!"), {})]

    asyncio.run(_scenario())
