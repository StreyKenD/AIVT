from __future__ import annotations

import psutil
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

REQUEST_LATENCY = Histogram(
    "kitsu_request_latency_seconds",
    "Latency per orchestrator pipeline stage",
    labelnames=("stage",),
    registry=REGISTRY,
)

WORKER_FAILURES = Counter(
    "kitsu_worker_failures_total",
    "Total worker failures observed by the orchestrator",
    labelnames=("worker",),
    registry=REGISTRY,
)

CPU_USAGE = Gauge(
    "kitsu_system_cpu_percent",
    "System-wide CPU utilisation percentage",
    registry=REGISTRY,
)

MEM_USAGE = Gauge(
    "kitsu_system_memory_percent",
    "System-wide memory utilisation percentage",
    registry=REGISTRY,
)


def observe_latency(stage: str, latency_seconds: float) -> None:
    """Record latency for the given pipeline stage in seconds."""
    REQUEST_LATENCY.labels(stage=stage).observe(max(0.0, latency_seconds))


def record_failure(worker: str) -> None:
    """Increment the failure counter for a worker component."""
    WORKER_FAILURES.labels(worker=worker).inc()


def refresh_system_gauges() -> None:
    """Refresh CPU and memory gauges from psutil."""
    try:
        CPU_USAGE.set(psutil.cpu_percent(interval=None))
        MEM_USAGE.set(psutil.virtual_memory().percent)
    except Exception:  # pragma: no cover - best effort
        return


def render_prometheus() -> bytes:
    """Return the latest metrics payload encoded in Prometheus plaintext format."""
    refresh_system_gauges()
    return generate_latest(REGISTRY)


__all__ = [
    "observe_latency",
    "record_failure",
    "render_prometheus",
    "refresh_system_gauges",
]
