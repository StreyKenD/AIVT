from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Protocol

logger = logging.getLogger("kitsu.telemetry.gpu")


class TelemetryPublisher(Protocol):
    async def publish(self, event_type: str, payload: dict[str, object]) -> None: ...

    async def aclose(self) -> None: ...


class GPUMonitor:
    """Publishes GPU metrics via telemetry (NVML)."""

    def __init__(
        self,
        telemetry: Optional[TelemetryPublisher],
        *,
        interval_seconds: float = 30.0,
        nvml: Any | None = None,
    ) -> None:
        self._telemetry = telemetry
        self._interval = max(5.0, float(interval_seconds))
        self._nvml = nvml
        self._task: asyncio.Task[None] | None = None
        self._initialized = False
        self._shutdown = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._telemetry is None:
            logger.info("GPU monitor disabled: telemetry unavailable")
            return
        async with self._lock:
            if self._task is not None:
                return
            if self._nvml is None:
                self._nvml = _load_nvml()
            if self._nvml is None:
                logger.info("GPU monitor disabled: pynvml not found")
                return
            try:
                self._nvml.nvmlInit()  # type: ignore[attr-defined]
                self._initialized = True
            except Exception as exc:  # pragma: no cover - environment without GPU
                logger.debug("Failed to initialize NVML: %s", exc)
                return
            self._task = asyncio.create_task(self._runner())

    async def stop(self) -> None:
        async with self._lock:
            task = self._task
            self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:  # pragma: no cover - expected cancellation
                pass
        if self._initialized and self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()  # type: ignore[attr-defined]
            except Exception:  # pragma: no cover - defensive shutdown
                logger.debug("Error shutting down NVML", exc_info=True)
        self._initialized = False
        self._nvml = None
        if self._telemetry is not None:
            await self._telemetry.aclose()

    async def collect_once(self) -> None:
        if self._telemetry is None or self._nvml is None:
            return
        payloads = _collect_metrics(self._nvml)
        for payload in payloads:
            try:
                await self._telemetry.publish("hardware.gpu", payload)
            except Exception as exc:  # pragma: no cover - external failure
                logger.debug("Error publishing GPU metrics: %s", exc)

    async def _runner(self) -> None:
        try:
            while True:
                await self.collect_once()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - safety loop
            logger.exception("GPU monitor loop failed")
        finally:
            if self._initialized and self._nvml is not None:
                try:
                    self._nvml.nvmlShutdown()  # type: ignore[attr-defined]
                except Exception:
                    logger.debug("Error shutting down NVML", exc_info=True)
                self._initialized = False
                self._nvml = None


def _load_nvml() -> Any | None:
    try:
        import pynvml  # type: ignore
    except ModuleNotFoundError:
        return None
    return pynvml


def _collect_metrics(nvml: Any) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    try:
        count = nvml.nvmlDeviceGetCount()  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - inconsistent NVML
        logger.debug("NVML unavailable: %s", exc)
        return payloads

    for index in range(count):
        try:
            handle = nvml.nvmlDeviceGetHandleByIndex(index)  # type: ignore[attr-defined]
            name = nvml.nvmlDeviceGetName(handle).decode("utf-8", "ignore")  # type: ignore[attr-defined]
            temp = float(nvml.nvmlDeviceGetTemperature(handle, 0))  # type: ignore[attr-defined]
            util = nvml.nvmlDeviceGetUtilizationRates(handle)  # type: ignore[attr-defined]
            mem = nvml.nvmlDeviceGetMemoryInfo(handle)  # type: ignore[attr-defined]
            fan_speed = _safe_nvml_call(nvml, "nvmlDeviceGetFanSpeed", handle)
            power = _safe_nvml_call(nvml, "nvmlDeviceGetPowerUsage", handle)
        except Exception as exc:  # pragma: no cover - specific GPU failed
            logger.debug("Error collecting data for GPU %s: %s", index, exc)
            continue

        used_mb = round(mem.used / (1024 * 1024), 2)
        total_mb = max(1.0, round(mem.total / (1024 * 1024), 2))
        free_mb = round(mem.free / (1024 * 1024), 2)
        power_w = round(power / 1000.0, 2) if isinstance(power, (int, float)) else None
        fan_pct = float(fan_speed) if isinstance(fan_speed, (int, float)) else None
        payload: dict[str, object] = {
            "index": index,
            "name": name,
            "temperature_c": temp,
            "utilization_pct": float(util.gpu),  # type: ignore[attr-defined]
            "memory_used_mb": used_mb,
            "memory_total_mb": total_mb,
            "memory_free_mb": free_mb,
            "memory_pct": round((used_mb / total_mb) * 100, 2) if total_mb else 0.0,
            "fan_speed_pct": fan_pct,
            "power_w": power_w,
        }
        payloads.append(payload)
    return payloads


def _safe_nvml_call(nvml: Any, func: str, handle: Any) -> float | int | None:
    try:
        method = getattr(nvml, func)
    except AttributeError:
        return None
    try:
        return method(handle)
    except Exception:
        return None


__all__ = ["GPUMonitor"]
