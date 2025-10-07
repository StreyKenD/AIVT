"""Camada de persistência da telemetria."""
from __future__ import annotations

import csv
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Sequence

import aiosqlite

_DB_ENV_VAR = "TELEMETRY_DB_PATH"
_DEFAULT_DB_PATH = "telemetry.db"


@dataclass(slots=True)
class TelemetryEvent:
    """Representa um evento recebido pela API de telemetria."""

    source: str
    event_type: str
    payload: dict[str, Any]
    created_at: str | None = None


def _resolve_db_path(db_path: str | None = None) -> str:
    path = Path(db_path or os.getenv(_DB_ENV_VAR, _DEFAULT_DB_PATH))
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


async def init_db(db_path: str | None = None) -> None:
    """Garante que a tabela de eventos exista."""

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
    """Insere um evento na base e retorna o ID criado."""

    database_path = _resolve_db_path(db_path)
    async with aiosqlite.connect(database_path) as conn:
        cursor = await conn.execute(
            """
            INSERT INTO telemetry_events (source, event_type, payload)
            VALUES (?, ?, ?)
            """,
            (event.source, event.event_type, json.dumps(event.payload, ensure_ascii=False)),
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
    """Retorna eventos com filtros opcionais."""

    database_path = _resolve_db_path(db_path)
    query = [
        "SELECT source, event_type, payload, COALESCE(created_at, '')",
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
        events.append(
            TelemetryEvent(
                source=row["source"],
                event_type=row["event_type"],
                payload=json.loads(row["payload"]),
                created_at=row["created_at"],
            )
        )
    return events


async def stream_events_as_csv(
    *, db_path: str | None = None, fieldnames: Sequence[str] | None = None
) -> AsyncIterator[str]:
    """Gera o conteúdo CSV em streaming."""

    database_path = _resolve_db_path(db_path)
    header = list(fieldnames or ("id", "source", "event_type", "payload", "created_at"))
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(header)
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)

    async with aiosqlite.connect(database_path) as conn:
        async with conn.execute(
            "SELECT id, source, event_type, payload, COALESCE(created_at, '') FROM telemetry_events ORDER BY id DESC"
        ) as cursor:
            async for row in cursor:
                payload = row[3]
                try:
                    payload_obj = json.loads(payload)
                    payload = json.dumps(payload_obj, ensure_ascii=False)
                except json.JSONDecodeError:
                    payload = str(payload)
                writer.writerow([row[0], row[1], row[2], payload, row[4]])
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate(0)


async def export_events(
    *, db_path: str | None = None, fieldnames: Sequence[str] | None = None
) -> str:
    """Exporta todos os eventos em uma única string CSV (útil para testes)."""

    chunks: list[str] = []
    async for chunk in stream_events_as_csv(db_path=db_path, fieldnames=fieldnames):
        chunks.append(chunk)
    return "".join(chunks)
