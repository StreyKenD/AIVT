"""Aplicação FastAPI responsável pela telemetria."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import storage


class TelemetryIn(BaseModel):
    source: str = Field(..., description="Origem do evento (ex.: obs, bot)")
    event_type: str = Field(..., description="Tipo do evento (ex.: frame, emotion)")
    payload: dict[str, Any] = Field(default_factory=dict, description="Dados associados")


class TelemetryOut(TelemetryIn):
    created_at: datetime | None = Field(None, description="Timestamp de criação")

    @classmethod
    def from_storage(cls, event: storage.TelemetryEvent) -> "TelemetryOut":
        created_at: datetime | None = None
        if event.created_at:
            try:
                created_at = datetime.fromisoformat(event.created_at)
            except ValueError:
                created_at = None
        return cls(
            source=event.source,
            event_type=event.event_type,
            payload=event.payload,
            created_at=created_at,
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    await storage.init_db()
    yield


app = FastAPI(title="Kitsu Telemetry API", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/events", response_model=dict[str, int])
async def ingest_event(event: TelemetryIn) -> dict[str, int]:
    telemetry = storage.TelemetryEvent(
        source=event.source,
        event_type=event.event_type,
        payload=event.payload,
    )
    event_id = await storage.insert_event(telemetry)
    return {"id": event_id}


@app.get("/events", response_model=list[TelemetryOut])
async def get_events(
    *,
    limit: int | None = Query(None, ge=1, le=500),
    event_type: str | None = None,
    source: str | None = None,
) -> list[TelemetryOut]:
    events = await storage.list_events(limit=limit, event_type=event_type, source=source)
    return [TelemetryOut.from_storage(event) for event in events]


@app.get("/events/export")
async def export_events() -> StreamingResponse:
    async def csv_generator():
        async for chunk in storage.stream_events_as_csv():
            yield chunk

    headers = {"Content-Disposition": "attachment; filename=telemetry_events.csv"}
    return StreamingResponse(csv_generator(), media_type="text/csv", headers=headers)
