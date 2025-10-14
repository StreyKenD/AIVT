from __future__ import annotations

import asyncio
from types import SimpleNamespace

from libs.telemetry.gpu import GPUMonitor


class DummyTelemetry:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
        self.closed = False

    async def publish(self, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((event_type, payload))

    async def aclose(self) -> None:
        self.closed = True


class FakeNVML:
    def __init__(self) -> None:
        self.initialized = False
        self.shutdown = False

    def nvmlInit(self) -> None:  # noqa: N802 - API externa
        self.initialized = True

    def nvmlShutdown(self) -> None:  # noqa: N802 - API externa
        self.shutdown = True

    def nvmlDeviceGetCount(self) -> int:  # noqa: N802
        return 1

    def nvmlDeviceGetHandleByIndex(self, index: int) -> int:  # noqa: N802
        return index

    def nvmlDeviceGetName(self, handle: int) -> bytes:  # noqa: N802
        return b"Mock GPU"

    def nvmlDeviceGetTemperature(self, handle: int, sensor: int) -> int:  # noqa: N802
        return 60

    def nvmlDeviceGetUtilizationRates(
        self, handle: int
    ) -> SimpleNamespace:  # noqa: N802
        return SimpleNamespace(gpu=75.0)

    def nvmlDeviceGetMemoryInfo(self, handle: int) -> SimpleNamespace:  # noqa: N802
        return SimpleNamespace(
            used=4 * 1024 * 1024,
            total=8 * 1024 * 1024,
            free=4 * 1024 * 1024,
        )

    def nvmlDeviceGetFanSpeed(self, handle: int) -> int:  # noqa: N802
        return 45

    def nvmlDeviceGetPowerUsage(self, handle: int) -> int:  # noqa: N802
        return 120000


def test_gpu_monitor_collect_and_publish() -> None:
    telemetry = DummyTelemetry()
    nvml = FakeNVML()
    monitor = GPUMonitor(telemetry, interval_seconds=5.0, nvml=nvml)

    asyncio.run(monitor.collect_once())

    assert telemetry.events, "esperava pelo menos um evento de GPU"
    event_type, payload = telemetry.events[0]
    assert event_type == "hardware.gpu"
    assert payload["name"] == "Mock GPU"
    assert payload["temperature_c"] == 60
    assert payload["utilization_pct"] == 75.0
    assert payload["memory_pct"] == 50.0
    assert payload["power_w"] == 120.0
    assert payload["fan_speed_pct"] == 45.0


def test_gpu_monitor_start_and_stop_handles_nvml() -> None:
    telemetry = DummyTelemetry()
    nvml = FakeNVML()
    monitor = GPUMonitor(telemetry, interval_seconds=5.0, nvml=nvml)

    async def _scenario() -> None:
        await monitor.start()
        assert nvml.initialized is True
        await asyncio.sleep(0)
        await monitor.stop()

    asyncio.run(_scenario())
    assert nvml.shutdown is True
    assert telemetry.closed is True
