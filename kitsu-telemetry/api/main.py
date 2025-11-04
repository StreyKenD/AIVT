"""FastAPI application responsible for telemetry."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from . import storage
from .log_reader import LogReaderError, query_logs

_DEFAULT_ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
}
_API_KEY = os.getenv("TELEMETRY_API_KEY")
_RETENTION_SECONDS = int(os.getenv("TELEMETRY_RETENTION_SECONDS", "0") or 0)


class TelemetryEventIn(BaseModel):
    type: str = Field(..., description="Event type (e.g. frame, emotion)")
    ts: datetime = Field(..., description="Event timestamp")
    payload: dict[str, Any] = Field(default_factory=dict, description="Associated data")
    source: str | None = Field(None, description="Optional event source")

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("type must be a non-empty string")
        return value

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("payload must be an object")
        return value


class LegacyTelemetryIn(BaseModel):
    source: str = Field(..., description="Event source (legacy)")
    event_type: str = Field(..., description="Event type (legacy)")
    payload: dict[str, Any] = Field(default_factory=dict, description="Associated data")
    created_at: datetime | None = Field(None, description="Optional legacy timestamp")

    @field_validator("event_type")
    @classmethod
    def _validate_event_type(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("event_type must be a non-empty string")
        return value

    @field_validator("payload")
    @classmethod
    def _validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("payload must be an object")
        return value


class TelemetryOut(BaseModel):
    type: str = Field(..., description="Event type")
    ts: str = Field(..., description="Event timestamp in ISO-8601 format")
    payload: dict[str, Any] = Field(default_factory=dict, description="Associated data")

    @classmethod
    def from_storage(cls, event: storage.TelemetryEvent) -> "TelemetryOut":
        return cls(type=event.type, ts=event.ts, payload=event.payload)


class LogEntryOut(BaseModel):
    ts: str = Field(..., description="Event timestamp in ISO-8601 format")
    service: str = Field(..., description="Service emitting the log line")
    level: str = Field(..., description="Log level")
    message: str = Field(..., description="Log message")
    logger: str | None = Field(None, description="Logger name")
    extra: dict[str, Any] | None = Field(None, description="Structured extras")
    exception: str | None = Field(None, description="Exception information, if present")
    file: str = Field(..., description="Log file relative path")


async def _require_api_key(x_api_key: str | None = Header(None)) -> None:
    if not _API_KEY:
        return
    if x_api_key != _API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def _load_allowed_origins() -> list[str]:
    env_value = os.getenv("TELEMETRY_ALLOWED_ORIGINS", "")
    origins = set(_DEFAULT_ALLOWED_ORIGINS)
    if env_value.strip():
        for origin in env_value.split(","):
            origin = origin.strip()
            if origin:
                origins.add(origin)
    return sorted(origins)


def _normalize_events(payload: Any) -> list[TelemetryEventIn]:
    if isinstance(payload, list):
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No event provided",
            )
        return [_coerce_event(item) for item in payload]
    return [_coerce_event(payload)]


def _coerce_event(item: Any) -> TelemetryEventIn:
    if not isinstance(item, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid event",
        )

    if "type" in item and "ts" in item:
        return TelemetryEventIn.model_validate(item)

    if "event_type" in item:
        legacy = LegacyTelemetryIn.model_validate(item)
        ts_value = legacy.created_at or datetime.now(timezone.utc)
        return TelemetryEventIn(
            type=legacy.event_type,
            ts=ts_value,
            payload=legacy.payload,
            source=legacy.source,
        )

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Invalid event: missing required fields",
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    await storage.init_db()
    yield


app = FastAPI(title="Kitsu Telemetry API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_load_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/events", response_model=dict[str, Any])
async def ingest_event(
    payload: Any = Body(...),
    _: None = Depends(_require_api_key),
) -> dict[str, Any]:
    events = _normalize_events(payload)
    ids: list[int] = []
    for event in events:
        telemetry = storage.TelemetryEvent(
            type=event.type,
            ts=event.ts.isoformat(),
            payload=event.payload,
            source=event.source,
        )
        event_id = await storage.insert_event(telemetry)
        ids.append(event_id)

    if _RETENTION_SECONDS:
        await storage.prune_events(_RETENTION_SECONDS)

    if len(ids) == 1:
        return {"id": ids[0]}
    return {"ids": ids}


@app.get("/events", response_model=list[TelemetryOut])
async def get_events(
    *,
    limit: int | None = Query(None, ge=1, le=500),
    type_: str | None = Query(None, alias="type"),
    event_type: str | None = None,
    source: str | None = None,
    _: None = Depends(_require_api_key),
) -> list[TelemetryOut]:
    effective_type = type_ or event_type
    events = await storage.list_events(limit=limit, event_type=effective_type, source=source)
    return [TelemetryOut.from_storage(event) for event in events]


@app.get("/events/export")
async def export_events(_: None = Depends(_require_api_key)) -> StreamingResponse:
    async def csv_generator():
        async for chunk in storage.stream_events_as_csv():
            yield chunk

    headers = {"Content-Disposition": "attachment; filename=telemetry_events.csv"}
    return StreamingResponse(csv_generator(), media_type="text/csv", headers=headers)


@app.get("/metrics/latest", response_model=dict[str, Any])
async def latest_metrics(
    window_seconds: int = Query(300, ge=60, le=7200),
    _: None = Depends(_require_api_key),
) -> dict[str, Any]:
    return await storage.latest_metrics(window_seconds=window_seconds)


@app.get("/logs", response_model=list[LogEntryOut])
async def list_logs(
    *,
    service: str | None = Query(None, description="Filter by service name"),
    level: str | None = Query(None, description="Filter by log level"),
    since: datetime | None = Query(None, description="Only entries newer than this timestamp"),
    contains: str | None = Query(None, description="Substring search across message and extras"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    limit: int = Query(200, ge=1, le=1000, description="Maximum number of log entries"),
    _: None = Depends(_require_api_key),
) -> list[LogEntryOut]:
    direction = order.lower()
    if direction not in {"asc", "desc"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="order must be 'asc' or 'desc'",
        )
    try:
        records = await asyncio.to_thread(
            query_logs,
            service=service,
            level=level,
            since=since,
            contains=contains,
            limit=limit,
            order=direction,
        )
    except LogReaderError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return [
        LogEntryOut(
            ts=record.ts.isoformat(),
            service=record.service,
            level=record.level,
            message=record.message,
            logger=record.logger,
            extra=record.extra,
            exception=record.exception,
            file=record.source_file,
        )
        for record in records
    ]


@app.post("/maintenance/prune", response_model=dict[str, Any])
async def manual_prune(
    max_age_seconds: int = Query(3600, ge=60),
    _: None = Depends(_require_api_key),
) -> dict[str, Any]:
    removed = await storage.prune_events(max_age_seconds)
    return {"removed": removed}
