"""Helpers for reading JSON log files produced by the runtime services."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator


@dataclass
class LogRecord:
    ts: datetime
    service: str
    level: str
    message: str
    logger: str | None
    extra: dict[str, Any] | None
    exception: str | None
    source_file: str
    raw: dict[str, Any]


class LogReaderError(RuntimeError):
    """Raised when the log reader cannot load data."""


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _expand_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    try:
        return path.resolve()
    except FileNotFoundError:
        return path


def _resolve_log_roots() -> list[Path]:
    env_value = os.getenv("KITSU_LOG_ROOT") or os.getenv("LOG_ROOT")
    if env_value:
        raw_values = [item.strip() for item in env_value.split(os.pathsep)]
        roots = [_expand_path(value) for value in raw_values if value]
        return _dedupe_paths(roots) or [_expand_path(Path.cwd() / "logs")]

    roots: list[Path] = [_expand_path(Path.cwd() / "logs")]
    sibling = Path.cwd().parent / "kitsu-vtuber-ai" / "logs"
    if sibling.exists():
        roots.append(_expand_path(sibling))
    return _dedupe_paths(roots)


def _iter_log_files(log_root: Path, service: str | None) -> Iterator[Path]:
    pattern = f"{service}.log*" if service else "*.log*"
    for path in sorted(
        log_root.glob(pattern),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        if path.is_file():
            yield path


def _parse_line(
    line: str,
    *,
    default_service: str | None,
    source_file: Path,
    base_path: Path,
) -> LogRecord | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    ts_raw = payload.get("ts")
    if not isinstance(ts_raw, str):
        return None
    ts_normalized = ts_raw.replace("Z", "+00:00")
    try:
        timestamp = datetime.fromisoformat(ts_normalized)
    except ValueError:
        return None

    service = str(payload.get("service") or default_service or "unknown")
    level = str(payload.get("level") or "info").lower()
    message = str(payload.get("message") or "")
    logger = payload.get("logger")
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else None
    exception = payload.get("exception")

    try:
        relative_source = os.path.relpath(source_file, base_path)
    except ValueError:
        relative_source = str(source_file)

    return LogRecord(
        ts=timestamp,
        service=service,
        level=level,
        message=message,
        logger=str(logger) if logger is not None else None,
        extra=extra,
        exception=str(exception) if exception is not None else None,
        source_file=relative_source,
        raw=payload,
    )


def query_logs(
    *,
    service: str | None = None,
    level: str | None = None,
    since: datetime | None = None,
    contains: str | None = None,
    limit: int = 200,
    order: str = "desc",
) -> list[LogRecord]:
    """
    Collect log entries from the JSON log files.

    Args:
        service: Optional service name filter.
        level: Optional log level filter (case-insensitive).
        since: Optional timestamp filter (only entries >= since).
        contains: Optional substring (case-insensitive) to search in message and extras.
        limit: Maximum number of entries to return.
        order: Either 'desc' (newest first) or 'asc' (oldest first).
    """

    if limit <= 0:
        return []

    log_roots = _resolve_log_roots()
    level_filter = level.lower() if level else None
    text_filter = contains.lower() if contains else None
    entries: list[LogRecord] = []

    files: list[tuple[Path, Path, float]] = []
    for index, log_root in enumerate(log_roots):
        if not log_root.exists():
            try:
                if index == 0:
                    log_root.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise LogReaderError(f"Log directory '{log_root}' does not exist") from exc
            if not log_root.exists():
                continue
        for log_file in _iter_log_files(log_root, service):
            try:
                mtime = log_file.stat().st_mtime
            except OSError:
                mtime = 0.0
            files.append((log_root, log_file, mtime))

    files.sort(key=lambda item: item[2], reverse=True)
    for base_path, log_file, _ in files:
        try:
            lines = log_file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise LogReaderError(f"Failed to read log file '{log_file}': {exc}") from exc

        default_service = log_file.stem.split(".")[0]
        for line in reversed(lines):
            record = _parse_line(
                line,
                default_service=default_service,
                source_file=log_file,
                base_path=base_path,
            )
            if record is None:
                continue

            if service and record.service != service:
                continue

            if level_filter and record.level != level_filter:
                continue

            if since and record.ts < since:
                # Remaining entries in this file are older because we are iterating backwards.
                break

            if text_filter and text_filter not in record.message.lower():
                extra_fragment = (
                    json.dumps(record.extra, ensure_ascii=False).lower()
                    if record.extra
                    else ""
                )
                if text_filter not in extra_fragment:
                    continue

            entries.append(record)
            if len(entries) >= limit and order == "desc":
                entries.sort(key=lambda item: item.ts, reverse=True)
                return entries[:limit]

    entries.sort(key=lambda item: item.ts, reverse=(order.lower() != "asc"))
    return entries[:limit]
