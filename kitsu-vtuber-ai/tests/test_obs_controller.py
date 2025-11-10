import asyncio
import os
import time

import pytest

from apps.obs_controller import main as obs_module


def test_obs_controller_dry_mode(monkeypatch) -> None:
    async def _scenario() -> None:
        monkeypatch.setattr(obs_module, "obsws", None)
        controller = obs_module.OBSController()
        await controller.ensure_connected()
        assert controller._connected.is_set()  # type: ignore[attr-defined]

        await controller.set_scene("Intro")
        await controller.toggle_filter("Mic", "NoiseGate", True)

    asyncio.run(_scenario())


def test_obs_controller_panic_invokes_toggle(monkeypatch) -> None:
    async def _scenario() -> None:
        controller = obs_module.OBSController()
        controller._connected.set()  # type: ignore[attr-defined]

        calls: list[tuple[str, str, bool]] = []

        async def fake_toggle(source: str, filter_name: str, enabled: bool) -> None:
            calls.append((source, filter_name, enabled))

        monkeypatch.setattr(controller, "toggle_filter", fake_toggle)
        await controller.panic()
        expected_filter = os.getenv("OBS_PANIC_FILTER", "HardMute")
        assert calls == [("Microphone", expected_filter, True)]

    asyncio.run(_scenario())


def test_obs_controller_non_blocking_calls(monkeypatch) -> None:
    class BlockingClient:
        def __init__(self, host: str, port: int, password: str) -> None:
            self.host = host
            self.port = port
            self.password = password
            self.calls = []

        def connect(self) -> None:
            time.sleep(0.2)

        def call(self, command: str, payload: dict[str, object]) -> dict[str, object]:
            time.sleep(0.2)
            self.calls.append((command, payload))
            return {"status": "ok"}

    async def _scenario() -> None:
        monkeypatch.setattr(obs_module, "obsws", BlockingClient)
        controller = obs_module.OBSController()

        start = time.perf_counter()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(controller.ensure_connected(), timeout=0.05)
        duration = time.perf_counter() - start
        assert duration < 0.2

        await asyncio.wait_for(controller.ensure_connected(), timeout=1.0)
        assert controller._connected.is_set()  # type: ignore[attr-defined]

        start = time.perf_counter()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(controller.set_scene("Intro"), timeout=0.05)
        duration = time.perf_counter() - start
        assert duration < 0.2

        await asyncio.sleep(0.3)
        await asyncio.wait_for(controller.set_scene("Intro"), timeout=1.0)
        assert controller._client is not None
        assert controller._client.calls  # type: ignore[attr-defined]
        command, payload = controller._client.calls[-1]  # type: ignore[attr-defined]
        assert command == "SetCurrentProgramScene"
        assert payload["sceneName"] == "Intro"

    asyncio.run(_scenario())
