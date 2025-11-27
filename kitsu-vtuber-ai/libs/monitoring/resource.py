from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Optional

import psutil

try:  # pragma: no cover - optional GPU support
    import pynvml
except ModuleNotFoundError:  # pragma: no cover - env without NVML
    pynvml = None  # type: ignore


class ResourceBusyError(RuntimeError):
    """Raised when a worker remains overloaded beyond the allowed timeout."""


@dataclass
class ResourceSnapshot:
    cpu_percent: float
    gpu_percent: Optional[float]
    timestamp: float


class ResourceMonitor:
    """Tracks CPU/GPU utilisation and exposes throttling helpers."""

    def __init__(
        self,
        *,
        cpu_threshold: float = 85.0,
        gpu_threshold: float = 90.0,
        sample_interval: float = 1.0,
    ) -> None:
        self._cpu_threshold = float(cpu_threshold)
        self._gpu_threshold = float(gpu_threshold)
        self._sample_interval = max(0.25, float(sample_interval))
        self._snapshot = ResourceSnapshot(cpu_percent=0.0, gpu_percent=None, timestamp=0.0)
        self._lock = asyncio.Lock()
        self._nvml = None
        if pynvml is not None:  # pragma: no mutate
            try:
                pynvml.nvmlInit()
                self._nvml = pynvml
            except Exception:  # pragma: no cover - GPU init failure
                self._nvml = None
        psutil.cpu_percent(interval=None)  # initialise first reading

    async def sample(self, *, force: bool = False) -> ResourceSnapshot:
        now = time.time()
        if not force and now - self._snapshot.timestamp < self._sample_interval:
            return self._snapshot
        async with self._lock:
            now = time.time()
            if not force and now - self._snapshot.timestamp < self._sample_interval:
                return self._snapshot
            cpu_pct = psutil.cpu_percent(interval=None)
            gpu_pct = self._read_gpu_percent()
            self._snapshot = ResourceSnapshot(cpu_percent=cpu_pct, gpu_percent=gpu_pct, timestamp=now)
            return self._snapshot

    def is_overloaded(self, snapshot: Optional[ResourceSnapshot] = None) -> bool:
        snap = snapshot or self._snapshot
        if snap.cpu_percent >= self._cpu_threshold:
            return True
        if snap.gpu_percent is not None and snap.gpu_percent >= self._gpu_threshold:
            return True
        return False

    async def wait_for_capacity(self, timeout: Optional[float] = None) -> None:
        if timeout is None or timeout <= 0:
            deadline = None
        else:
            deadline = time.time() + timeout
        while True:
            snapshot = await self.sample()
            if not self.is_overloaded(snapshot):
                return
            if deadline is not None and time.time() >= deadline:
                raise ResourceBusyError(
                    f"Resource usage remains above thresholds (cpu={snapshot.cpu_percent:.1f} gpu={snapshot.gpu_percent})"
                )
            await asyncio.sleep(self._sample_interval)

    def shutdown(self) -> None:
        if self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - defensive shutdown
                pass
            self._nvml = None

    def _read_gpu_percent(self) -> Optional[float]:
        if self._nvml is None:
            return None
        try:
            count = self._nvml.nvmlDeviceGetCount()  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - NVML failure
            return None
        if count <= 0:
            return None
        total = 0.0
        for index in range(count):
            try:
                handle = self._nvml.nvmlDeviceGetHandleByIndex(index)  # type: ignore[attr-defined]
                util = self._nvml.nvmlDeviceGetUtilizationRates(handle)  # type: ignore[attr-defined]
                total += float(util.gpu)
            except Exception:  # pragma: no cover - per device error
                continue
        if total <= 0.0:
            return 0.0
        return round(total / max(1, count), 2)


__all__ = ["ResourceMonitor", "ResourceSnapshot", "ResourceBusyError"]
