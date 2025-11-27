from __future__ import annotations

import asyncio
from typing import Any

import pytest

from libs.monitoring.resource import ResourceBusyError, ResourceMonitor


@pytest.mark.asyncio()
async def test_wait_for_capacity_handles_overload(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_cpu_percent(interval: Any = None) -> float:
        return 95.0

    monkeypatch.setattr("libs.monitoring.resource.psutil.cpu_percent", fake_cpu_percent)
    monitor = ResourceMonitor(cpu_threshold=50.0, gpu_threshold=100.0, sample_interval=0.01)
    with pytest.raises(ResourceBusyError):
        await monitor.wait_for_capacity(timeout=0.05)
    monitor.shutdown()


@pytest.mark.asyncio()
async def test_wait_for_capacity_eventually_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    values = [90.0, 40.0]

    def fake_cpu_percent(interval: Any = None) -> float:
        return values.pop(0) if values else 10.0

    monkeypatch.setattr("libs.monitoring.resource.psutil.cpu_percent", fake_cpu_percent)
    monitor = ResourceMonitor(cpu_threshold=80.0, gpu_threshold=100.0, sample_interval=0.01)
    await monitor.wait_for_capacity(timeout=0.1)
    monitor.shutdown()
