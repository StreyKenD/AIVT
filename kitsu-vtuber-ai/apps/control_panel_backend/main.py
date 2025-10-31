from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi import status as http_status
from fastapi.responses import StreamingResponse

from libs.contracts import MuteCommand, PanicCommand, PresetCommand

from libs.common import configure_json_logging

_ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_BASE_URL", "http://127.0.0.1:8000")
_TELEMETRY_URL = os.getenv("TELEMETRY_BASE_URL", "http://127.0.0.1:8001")
_ORCHESTRATOR_TOKEN = os.getenv("ORCHESTRATOR_API_KEY")
_TELEMETRY_API_KEY = os.getenv("TELEMETRY_API_KEY")

_REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


configure_json_logging("control_panel_backend")
logger = logging.getLogger("kitsu.control_panel")


class ControlPanelGateway:
    """Facilitates communication with the orchestrator and telemetry API."""

    def __init__(self, orchestrator_url: str, telemetry_url: str) -> None:
        self._orch_client = httpx.AsyncClient(
            base_url=orchestrator_url.rstrip("/"), timeout=_REQUEST_TIMEOUT
        )
        self._telemetry_client = httpx.AsyncClient(
            base_url=telemetry_url.rstrip("/"), timeout=_REQUEST_TIMEOUT
        )

    async def close(self) -> None:
        await self._orch_client.aclose()
        await self._telemetry_client.aclose()

    async def orchestrator_get(self, path: str) -> Dict[str, Any]:
        headers = _build_orchestrator_headers()
        response = await self._orch_client.get(path, headers=headers)
        data = _parse_json(response)
        if not isinstance(data, dict):
            raise HTTPException(
                status_code=500, detail="Unexpected response from the orchestrator"
            )
        return data

    async def orchestrator_post(
        self, path: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        headers = _build_orchestrator_headers()
        response = await self._orch_client.post(path, json=payload, headers=headers)
        data = _parse_json(response)
        if not isinstance(data, dict):
            raise HTTPException(
                status_code=500, detail="Unexpected response from the orchestrator"
            )
        return data

    async def telemetry_get(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        headers = _build_telemetry_headers()
        response = await self._telemetry_client.get(
            path, headers=headers, params=params or {}
        )
        return _parse_json(response)

    async def telemetry_stream(self, path: str) -> AsyncIterator[bytes]:
        headers = _build_telemetry_headers()
        async with self._telemetry_client.stream(
            "GET", path, headers=headers
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                yield chunk


def _build_orchestrator_headers() -> Dict[str, str]:
    if not _ORCHESTRATOR_TOKEN:
        return {"Content-Type": "application/json"}
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_ORCHESTRATOR_TOKEN}",
    }


def _build_telemetry_headers() -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    if _TELEMETRY_API_KEY:
        headers["X-API-Key"] = _TELEMETRY_API_KEY
    return headers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    gateway = ControlPanelGateway(_ORCHESTRATOR_URL, _TELEMETRY_URL)
    logger.info(
        "Control backend ready",
        extra={"orchestrator": _ORCHESTRATOR_URL, "telemetry": _TELEMETRY_URL},
    )
    app.state.gateway = gateway
    try:
        yield
    finally:
        await gateway.close()


app = FastAPI(title="Kitsu Control Panel Backend", version="0.2.0", lifespan=lifespan)


async def get_gateway() -> ControlPanelGateway:
    gateway = getattr(app.state, "gateway", None)
    if gateway is None:
        raise RuntimeError("ControlPanelGateway not initialised")
    return gateway


@app.get("/status", response_model=Dict[str, Any])
async def status(
    gateway: ControlPanelGateway = Depends(get_gateway),
) -> Dict[str, Any]:
    orchestrator = await gateway.orchestrator_get("/status")
    metrics = await gateway.telemetry_get("/metrics/latest")
    return {"status": orchestrator, "metrics": metrics}


@app.get("/metrics/latest", response_model=Dict[str, Any])
async def metrics_latest(
    gateway: ControlPanelGateway = Depends(get_gateway),
    window_seconds: int = Query(300, ge=60, le=7200),
) -> Dict[str, Any]:
    return await gateway.telemetry_get(
        "/metrics/latest", params={"window_seconds": window_seconds}
    )


@app.get("/soak/results", response_model=Dict[str, Any])
async def soak_results(
    gateway: ControlPanelGateway = Depends(get_gateway),
    limit: int = Query(10, ge=1, le=50),
) -> Dict[str, Any]:
    events = await gateway.telemetry_get(
        "/events", params={"type": "soak.result", "limit": limit}
    )
    if not isinstance(events, list):
        raise HTTPException(status_code=500, detail="Unexpected response from telemetry")
    return {"items": events}


@app.get("/telemetry/export")
async def telemetry_export(
    gateway: ControlPanelGateway = Depends(get_gateway),
) -> StreamingResponse:
    async def _generator() -> AsyncIterator[bytes]:
        async for chunk in gateway.telemetry_stream("/events/export"):
            yield chunk

    headers = {"Content-Disposition": "attachment; filename=telemetry_events.csv"}
    return StreamingResponse(_generator(), headers=headers, media_type="text/csv")


@app.post(
    "/control/panic",
    response_model=Dict[str, Any],
    status_code=http_status.HTTP_202_ACCEPTED,
)
async def control_panic(
    payload: PanicCommand,
    gateway: ControlPanelGateway = Depends(get_gateway),
) -> Dict[str, Any]:
    return await gateway.orchestrator_post("/control/panic", payload.dict())


@app.post("/control/mute", response_model=Dict[str, Any])
async def control_mute(
    payload: MuteCommand,
    gateway: ControlPanelGateway = Depends(get_gateway),
) -> Dict[str, Any]:
    return await gateway.orchestrator_post("/control/mute", payload.dict())


@app.post("/control/preset", response_model=Dict[str, Any])
async def control_preset(
    payload: PresetCommand,
    gateway: ControlPanelGateway = Depends(get_gateway),
) -> Dict[str, Any]:
    return await gateway.orchestrator_post("/control/preset", payload.dict())


def _parse_json(response: httpx.Response) -> Any:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text or str(exc)
        raise HTTPException(status_code=exc.response.status_code, detail=detail)
    return response.json()
