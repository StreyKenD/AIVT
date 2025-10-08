"""Aplicação FastAPI responsável pela telemetria."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, validator

from . import storage

_DEFAULT_ALLOWED_ORIGIN = "http://localhost:5173"


class TelemetryEventIn(BaseModel):
    type: str = Field(..., description="Tipo do evento (ex.: frame, emotion)")
    ts: datetime = Field(..., description="Timestamp do evento")
    payload: dict[str, Any] = Field(default_factory=dict, description="Dados associados")
    source: str | None = Field(None, description="Origem opcional do evento")

    @validator("type")
    def _validate_type(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("type must be a non-empty string")
        return value

    @validator("payload")
    def _validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("payload must be an object")
        return value


class LegacyTelemetryIn(BaseModel):
    source: str = Field(..., description="Origem do evento (legado)")
    event_type: str = Field(..., description="Tipo do evento (legado)")
    payload: dict[str, Any] = Field(default_factory=dict, description="Dados associados")
    created_at: datetime | None = Field(None, description="Timestamp opcional do legado")

    @validator("event_type")
    def _validate_event_type(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("event_type must be a non-empty string")
        return value

    @validator("payload")
    def _validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("payload must be an object")
        return value


class TelemetryOut(BaseModel):
    type: str = Field(..., description="Tipo do evento")
    ts: str = Field(..., description="Timestamp do evento em formato ISO-8601")
    payload: dict[str, Any] = Field(default_factory=dict, description="Dados associados")

    @classmethod
    def from_storage(cls, event: storage.TelemetryEvent) -> "TelemetryOut":
        return cls(type=event.type, ts=event.ts, payload=event.payload)


def _load_allowed_origins() -> list[str]:
    env_value = os.getenv("TELEMETRY_ALLOWED_ORIGINS", "")
    if not env_value.strip():
        return [_DEFAULT_ALLOWED_ORIGIN]
    origins = [origin.strip() for origin in env_value.split(",")]
    filtered = [origin for origin in origins if origin]
    return filtered or [_DEFAULT_ALLOWED_ORIGIN]


def _normalize_events(payload: Any) -> list[TelemetryEventIn]:
    if isinstance(payload, list):
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nenhum evento fornecido",
            )
        return [_coerce_event(item) for item in payload]
    return [_coerce_event(payload)]


def _coerce_event(item: Any) -> TelemetryEventIn:
    if not isinstance(item, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Evento inválido",
        )

    if "type" in item and "ts" in item:
        return TelemetryEventIn.parse_obj(item)

    if "event_type" in item:
        legacy = LegacyTelemetryIn.parse_obj(item)
        ts_value = legacy.created_at or datetime.utcnow()
        return TelemetryEventIn(
            type=legacy.event_type,
            ts=ts_value,
            payload=legacy.payload,
            source=legacy.source,
        )

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Evento inválido: campos obrigatórios ausentes",
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
async def ingest_event(payload: Any = Body(...)) -> dict[str, Any]:
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
) -> list[TelemetryOut]:
    effective_type = type_ or event_type
    events = await storage.list_events(limit=limit, event_type=effective_type, source=source)
    return [TelemetryOut.from_storage(event) for event in events]


@app.get("/events/export")
async def export_events() -> StreamingResponse:
    async def csv_generator():
        async for chunk in storage.stream_events_as_csv():
            yield chunk

    headers = {"Content-Disposition": "attachment; filename=telemetry_events.csv"}
    return StreamingResponse(csv_generator(), media_type="text/csv", headers=headers)
