import asyncio

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
