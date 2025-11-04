from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api.log_reader import query_logs


def _append_log(
    path: Path,
    *,
    service: str,
    ts: datetime,
    message: str,
    level: str = "info",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": ts.isoformat(),
        "service": service,
        "level": level,
        "message": message,
        "logger": f"{service}.logger",
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def test_query_logs_reads_from_runtime_sibling(monkeypatch, tmp_path) -> None:
    telemetry_root = tmp_path / "kitsu-telemetry"
    telemetry_logs = telemetry_root / "logs"
    telemetry_logs.mkdir(parents=True)

    runtime_root = tmp_path / "kitsu-vtuber-ai" / "logs"
    runtime_log = runtime_root / "orchestrator.log"
    timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    _append_log(
        runtime_log,
        service="orchestrator",
        ts=timestamp,
        message="runtime entry",
    )

    monkeypatch.chdir(telemetry_root)
    monkeypatch.delenv("KITSU_LOG_ROOT", raising=False)
    monkeypatch.delenv("LOG_ROOT", raising=False)

    records = query_logs(limit=5)
    assert [record.service for record in records] == ["orchestrator"]
    assert records[0].source_file == "orchestrator.log"


def test_query_logs_merges_multiple_roots(monkeypatch, tmp_path) -> None:
    telemetry_root = tmp_path / "kitsu-telemetry"
    telemetry_logs = telemetry_root / "logs"
    telemetry_logs.mkdir(parents=True)

    runtime_root = tmp_path / "kitsu-vtuber-ai" / "logs"
    runtime_logs = runtime_root

    base_time = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    _append_log(
        telemetry_logs / "telemetry.log",
        service="telemetry",
        ts=base_time - timedelta(minutes=5),
        message="telemetry entry",
    )
    _append_log(
        runtime_logs / "orchestrator.log",
        service="orchestrator",
        ts=base_time,
        message="orchestrator entry",
    )

    monkeypatch.chdir(telemetry_root)
    monkeypatch.delenv("KITSU_LOG_ROOT", raising=False)
    monkeypatch.delenv("LOG_ROOT", raising=False)

    records = query_logs(limit=2)
    assert [record.service for record in records] == ["orchestrator", "telemetry"]


def test_query_logs_honors_env_overrides(monkeypatch, tmp_path) -> None:
    first_root = tmp_path / "root_one"
    second_root = tmp_path / "root_two"
    first_log = first_root / "first.log"
    second_log = second_root / "second.log"

    base_time = datetime(2025, 1, 2, 8, 0, tzinfo=timezone.utc)
    _append_log(
        first_log,
        service="alpha",
        ts=base_time,
        message="alpha entry",
    )
    _append_log(
        second_log,
        service="beta",
        ts=base_time + timedelta(minutes=1),
        message="beta entry",
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "KITSU_LOG_ROOT",
        os.pathsep.join([str(second_root), str(first_root)]),
    )
    monkeypatch.delenv("LOG_ROOT", raising=False)

    records = query_logs(limit=2)
    assert [record.service for record in records] == ["beta", "alpha"]
