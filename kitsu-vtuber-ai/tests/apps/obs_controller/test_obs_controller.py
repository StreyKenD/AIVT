import types

import pytest

from apps.obs_controller import main as obs_main


class DummyOBSClient:
    def __init__(self, host: str, port: int, password: str) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.connected = False
        self.calls = []

    def connect(self) -> None:
        self.connected = True

    def call(self, method: str, payload: dict[str, object]) -> None:
        self.calls.append((method, payload))


async def _immediate_run_blocking(self, func, *args, **kwargs):
    return func(*args, **kwargs)


@pytest.mark.asyncio()
async def test_ensure_connected_dry_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """When obsws is missing the controller should enter dry mode quickly."""
    monkeypatch.setattr(obs_main, "obsws", None)
    controller = obs_main.OBSController()
    await controller.ensure_connected()
    assert controller._connected.is_set()


@pytest.mark.asyncio()
async def test_set_scene_invokes_obs_call(monkeypatch: pytest.MonkeyPatch) -> None:
    dummy = DummyOBSClient("127.0.0.1", 4455, "")

    def fake_obsws(host: str, port: int, password: str) -> DummyOBSClient:
        assert host == "127.0.0.1"
        assert port == 4455
        assert password == ""
        return dummy

    monkeypatch.setattr(obs_main, "obsws", fake_obsws)
    controller = obs_main.OBSController()
    controller._run_blocking = types.MethodType(_immediate_run_blocking, controller)

    await controller.connect()
    await controller.set_scene("Gameplay")

    assert dummy.connected is True
    assert dummy.calls == [
        (
            "SetCurrentProgramScene",
            {"sceneName": "Gameplay"},
        )
    ]


@pytest.mark.asyncio()
async def test_panic_triggers_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = obs_main.OBSController()
    called: dict[str, tuple[str, str, bool]] = {}

    async def fake_toggle(self, source: str, filter_name: str, enabled: bool) -> None:
        called["args"] = (source, filter_name, enabled)

    controller.toggle_filter = types.MethodType(fake_toggle, controller)
    monkeypatch.setenv("OBS_PANIC_FILTER", "MegaMute")

    await controller.panic()

    assert called["args"] == ("Microphone", "MegaMute", True)
