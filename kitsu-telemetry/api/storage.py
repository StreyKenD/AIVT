"""Telemetry persistence layer."""
from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Sequence

import aiosqlite

_DB_ENV_VAR = "TELEMETRY_DB_PATH"
_DEFAULT_DB_PATH = "telemetry.db"
_DEFAULT_CSV_HEADER = ("ts", "type", "json_payload")
_NUMERIC_SUFFIXES = ("_ms", "_pct", "_c", "_w", "_mb")


@dataclass(slots=True)
class TelemetryEvent:
    """Represents an event received by the telemetry API."""

    type: str
    ts: str
    payload: dict[str, Any]
    id: int | None = None
    source: str | None = None


def _resolve_db_path(db_path: str | None = None) -> str:
    path = Path(db_path or os.getenv(_DB_ENV_VAR, _DEFAULT_DB_PATH))
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(value: Any) -> str:
    if value is None:
        return _format_timestamp(_utcnow())
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return _format_timestamp(_utcnow())
        candidate = raw.replace("Z", "+00:00").replace(" ", "T")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return raw
        return parsed.isoformat()
    return _format_timestamp(_utcnow())


def _accumulate_numeric(bucket: dict[str, Any], key: str, value: Any) -> None:
    if value is None or isinstance(value, bool):
        return
    try:
        number = float(value)
    except (TypeError, ValueError):
        return
    stats = bucket.setdefault(
        key,
        {"sum": 0.0, "max": number, "min": number, "_count": 0},
    )
    stats["_count"] += 1
    stats["sum"] += number
    stats["max"] = max(stats["max"], number)
    stats["min"] = min(stats["min"], number)


async def init_db(db_path: str | None = None) -> None:
    """Ensure the events table exists."""

    database_path = _resolve_db_path(db_path)
    async with aiosqlite.connect(database_path) as conn:
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await conn.commit()


async def insert_event(event: TelemetryEvent, db_path: str | None = None) -> int:
    """Insert an event into the database and return the created ID."""

    database_path = _resolve_db_path(db_path)
    async with aiosqlite.connect(database_path) as conn:
        cursor = await conn.execute(
            """
            INSERT INTO telemetry_events (source, event_type, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                event.source or "",
                event.type,
                json.dumps(event.payload, ensure_ascii=False),
                _format_timestamp(event.ts),
            ),
        )
        await conn.commit()
        return cursor.lastrowid


async def list_events(
    *,
    limit: int | None = None,
    event_type: str | None = None,
    source: str | None = None,
    db_path: str | None = None,
) -> list[TelemetryEvent]:
    """Return events filtered by optional criteria."""

    database_path = _resolve_db_path(db_path)
    query = [
        "SELECT id, source, event_type, payload, COALESCE(created_at, '') AS created_at",
        "FROM telemetry_events",
    ]
    clauses: list[str] = []
    params: list[Any] = []
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if source:
        clauses.append("source = ?")
        params.append(source)
    if clauses:
        query.append("WHERE " + " AND ".join(clauses))
    query.append("ORDER BY id DESC")
    if limit:
        query.append("LIMIT ?")
        params.append(limit)

    sql = " ".join(query)
    async with aiosqlite.connect(database_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

    events: list[TelemetryEvent] = []
    for row in rows:
        payload_raw = row["payload"]
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = {}
        events.append(
            TelemetryEvent(
                id=row["id"],
                source=row["source"] or None,
                type=row["event_type"],
                ts=_format_timestamp(row["created_at"]),
                payload=payload,
            )
        )
    return events


async def stream_events_as_csv(
    *, db_path: str | None = None, fieldnames: Sequence[str] | None = None
) -> AsyncIterator[str]:
    """Stream the CSV content."""

    database_path = _resolve_db_path(db_path)
    header = list(fieldnames or _DEFAULT_CSV_HEADER)
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(header)
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)

    async with aiosqlite.connect(database_path) as conn:
        async with conn.execute(
            "SELECT event_type, payload, COALESCE(created_at, '') FROM telemetry_events ORDER BY id DESC"
        ) as cursor:
            async for row in cursor:
                event_type, payload_serialized, created_at = row
                ts_value = _format_timestamp(created_at)
                try:
                    payload_obj = json.loads(payload_serialized)
                    payload_json = json.dumps(payload_obj, ensure_ascii=False)
                except json.JSONDecodeError:
                    payload_json = str(payload_serialized)
                writer.writerow([ts_value, event_type, payload_json])
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)


async def export_events(
    *, db_path: str | None = None, fieldnames: Sequence[str] | None = None
) -> str:
    """Export all events into a single CSV string (useful for tests)."""

    chunks: list[str] = []
    async for chunk in stream_events_as_csv(db_path=db_path, fieldnames=fieldnames):
        chunks.append(chunk)
    return "".join(chunks)


async def prune_events(max_age_seconds: int, db_path: str | None = None) -> int:
    """Remove events older than the configured limit."""

    if max_age_seconds <= 0:
        return 0
    cutoff = _utcnow() - timedelta(seconds=max_age_seconds)
    database_path = _resolve_db_path(db_path)
    async with aiosqlite.connect(database_path) as conn:
        cursor = await conn.execute(
            "DELETE FROM telemetry_events WHERE created_at < ?",
            (cutoff.isoformat(),),
        )
        await conn.commit()
        return cursor.rowcount or 0


async def latest_metrics(
    *, window_seconds: int = 300, db_path: str | None = None
) -> dict[str, Any]:
    """Calculate aggregated metrics for the provided sliding window."""

    window_seconds = max(60, int(window_seconds))
    cutoff = _utcnow() - timedelta(seconds=window_seconds)
    database_path = _resolve_db_path(db_path)
    sql = (
        "SELECT event_type, payload, COALESCE(created_at, '') "
        "FROM telemetry_events WHERE created_at >= ? ORDER BY id DESC"
    )
    metrics: dict[str, dict[str, Any]] = {}
    async with aiosqlite.connect(database_path) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(sql, (cutoff.isoformat(),)) as cursor:
            async for row in cursor:
                event_type = row["event_type"]
                raw_payload = row["payload"]
                try:
                    payload = json.loads(raw_payload)
                except json.JSONDecodeError:
                    payload = {}
                bucket = metrics.setdefault(event_type, {"count": 0})
                bucket["count"] += 1
                failures = payload.get("failures")
                if isinstance(failures, (int, float)):
                    bucket["failures"] = bucket.get("failures", 0) + int(failures)
                for key, value in payload.items():
                    if key == "failures":
                        continue
                    if any(key.endswith(suffix) for suffix in _NUMERIC_SUFFIXES):
                        _accumulate_numeric(bucket, key, value)
    for bucket in metrics.values():
        for key, value in list(bucket.items()):
            if not isinstance(value, dict) or "_count" not in value:
                continue
            count = value.pop("_count")
            if not count:
                bucket.pop(key)
                continue
            total = value.get("sum", 0.0)
            value["sum"] = round(total, 2)
            value["avg"] = round(total / count, 2)
            value["max"] = round(value["max"], 2)
            value["min"] = round(value["min"], 2)
    return {"window_seconds": window_seconds, "metrics": metrics}
