from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from libs.common import configure_json_logging

from .service import TTSResult, TTSService, get_tts_service

configure_json_logging("tts_worker")
logger = logging.getLogger("kitsu.tts")


app = FastAPI(title="Kitsu TTS Worker", version="0.2.0")

_service: Optional[TTSService] = None
_worker_task: Optional[asyncio.Task[None]] = None


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice: Optional[str] = Field(None, description="Preferred voice identifier")
    request_id: Optional[str] = Field(None, description="Optional correlation id")


class SpeakResponse(BaseModel):
    audio_path: str
    voice: str
    latency_ms: float
    visemes: list[Dict[str, float]]
    cached: bool


@app.on_event("startup")
async def startup() -> None:
    global _service, _worker_task
    if _service is not None:
        return
    service = get_tts_service()
    _service = service
    _worker_task = asyncio.create_task(service.worker())
    logger.info("TTS worker ready")


@app.on_event("shutdown")
async def shutdown() -> None:
    global _service, _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _worker_task
        _worker_task = None
    if _service is not None:
        with contextlib.suppress(Exception):
            await _service.cancel_active()
        _service = None


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/speak", response_model=SpeakResponse)
async def speak(request: SpeakRequest) -> SpeakResponse:
    if _service is None:
        raise HTTPException(status_code=503, detail="TTS service unavailable")
    result: TTSResult = await _service.enqueue(
        request.text,
        voice=request.voice,
        request_id=request.request_id,
    )
    return SpeakResponse(
        audio_path=str(result.audio_path),
        voice=result.voice,
        latency_ms=result.latency_ms,
        visemes=result.visemes,
        cached=result.cached,
    )


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("TTS_HOST", "0.0.0.0")
    port = int(os.getenv("TTS_PORT", "8070"))
    uvicorn.run(
        "apps.tts_worker.main:app",
        host=host,
        port=port,
        reload=os.getenv("UVICORN_RELOAD") == "1",
    )
