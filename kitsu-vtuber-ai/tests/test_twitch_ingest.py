import asyncio
import os
from typing import Any, Dict, List, Optional

import pytest

from apps.twitch_ingest import main as twitch_module


class _StubBridge(twitch_module.TwitchBridge):
    def __init__(self) -> None:
        self.calls: List[tuple[str, Any]] = []

    async def toggle_tts(self, enabled: bool) -> None:
        self.calls.append(("toggle_tts", enabled))

    async def update_persona(
        self, *, style: Optional[str], chaos: Optional[float], energy: Optional[float]
    ) -> None:
        self.calls.append(
            (
                "update_persona",
                {
                    "style": style,
                    "chaos": chaos,
                    "energy": energy,
                },
            )
        )

    async def set_scene(self, scene: str) -> None:
        self.calls.append(("set_scene", scene))

    async def emit_chat(self, role: str, text: str) -> None:
        self.calls.append(("emit_chat", role, text))


@pytest.mark.asyncio()
async def test_twitch_router_dispatches_expected_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = _StubBridge()
    router = twitch_module.TwitchCommandRouter(bridge, cooldown_seconds=0.0)

    monkeypatch.setenv("TWITCH_DEFAULT_SCENE", "BRB")

    await router.handle(twitch_module.ChatMessage(author="fox", content="!mute"))
    await router.handle(twitch_module.ChatMessage(author="fox", content="!unmute"))
    await router.handle(twitch_module.ChatMessage(author="fox", content="!scene"))
    await router.handle(
        twitch_module.ChatMessage(author="fox", content="!style comfy 25 75")
    )
    await router.handle(
        twitch_module.ChatMessage(author="viewer", content="Hello Kitsu!")
    )

    assert ("toggle_tts", False) in bridge.calls
    assert ("toggle_tts", True) in bridge.calls
    assert ("set_scene", "BRB") in bridge.calls
    assert (
        "update_persona",
        {"style": "comfy", "chaos": 0.25, "energy": 0.75},
    ) in bridge.calls
    assert ("emit_chat", "user", "Hello Kitsu!") in bridge.calls


@pytest.mark.asyncio()
async def test_orchestrator_bridge_attaches_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_requests: List[Dict[str, Any]] = []

    class DummyClient:
        def __init__(self, *_, **__) -> None:
            self.closed = False

        async def post(
            self,
            path: str,
            *,
            json: Dict[str, Any],
            headers: Optional[Dict[str, str]] = None,
        ) -> None:
            captured_requests.append(
                {"path": path, "json": json, "headers": headers or {}}
            )

        async def aclose(self) -> None:
            self.closed = True

    dummy_client = DummyClient()

    def _fake_async_client(*args, **kwargs):
        assert kwargs["base_url"] == "http://localhost:8000"
        return dummy_client

    monkeypatch.setattr(twitch_module.httpx, "AsyncClient", _fake_async_client)

    bridge = twitch_module.OrchestratorBridge("http://localhost:8000", api_key="secret")
    await bridge.toggle_tts(True)
    await bridge.update_persona(style="kawaii", chaos=0.5, energy=None)
    await bridge.close()

    assert captured_requests
    for request in captured_requests:
        headers = request["headers"]
        assert headers.get("X-API-Key") == "secret"
        assert headers.get("Authorization") == "Bearer secret"
