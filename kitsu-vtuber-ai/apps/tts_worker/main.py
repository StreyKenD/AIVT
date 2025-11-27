from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException

from libs.common import configure_json_logging
from libs.config import get_app_config
from libs.contracts import TTSRequestPayload, TTSResponsePayload
from libs.monitoring.resource import ResourceBusyError
from libs.telemetry import TelemetryClient

from .service import TTSResult, TTSService, get_tts_service

configure_json_logging("tts_worker")
logger = logging.getLogger("kitsu.tts")


app = FastAPI(title="Kitsu TTS Worker", version="0.2.0")

_service: Optional[TTSService] = None
_worker_task: Optional[asyncio.Task[None]] = None
settings = get_app_config()
tts_cfg = settings.tts
orchestrator_cfg = settings.orchestrator
_telemetry_client = (
    TelemetryClient(
        orchestrator_cfg.telemetry_url,
        api_key=orchestrator_cfg.telemetry_api_key,
        source="tts_worker",
    )
    if orchestrator_cfg.telemetry_url
    else None
)


@app.on_event("startup")
async def startup() -> None:
    """Initialise the TTS queue worker and shared service instance."""
    global _service, _worker_task
    if _service is not None:
        return
    service = get_tts_service(config=tts_cfg, telemetry=_telemetry_client)
    _service = service
    _worker_task = asyncio.create_task(service.worker())
    logger.info("TTS worker ready")


@app.on_event("shutdown")
async def shutdown() -> None:
    """Dispose background tasks and reset the singleton service reference."""
    global _service, _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _worker_task
        _worker_task = None
    if _service is not None:
        with contextlib.suppress(Exception):
            await _service.cancel_active()
        _service.shutdown()
        _service = None


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/speak", response_model=TTSResponsePayload)
async def speak(request: TTSRequestPayload) -> TTSResponsePayload:
    """Synthesize speech for the provided text, returning a cached response when possible."""
    if _service is None:
        raise HTTPException(status_code=503, detail="TTS service unavailable")
    try:
        result: TTSResult = await _service.enqueue(
            request.text,
            voice=request.voice,
            request_id=request.request_id,
        )
    except ResourceBusyError:
        raise HTTPException(status_code=429, detail="tts_busy") from None
    return TTSResponsePayload(
        audio_path=str(result.audio_path),
        voice=result.voice,
        latency_ms=result.latency_ms,
        visemes=result.visemes,
        cached=result.cached,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "apps.tts_worker.main:app",
        host=tts_cfg.bind_host,
        port=tts_cfg.bind_port,
        reload=os.getenv("UVICORN_RELOAD") == "1",
    )
