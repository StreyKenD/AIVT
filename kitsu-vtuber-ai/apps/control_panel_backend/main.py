from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi import status as http_status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from libs.common import configure_json_logging
from libs.config import get_app_config
from libs.contracts import MuteCommand, PanicCommand, PresetCommand
from .ollama import OllamaSupervisor, parse_bool

_DEFAULT_ALLOWED_ORIGINS = {
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
}
try:
    _DEFAULT_ORCHESTRATOR_URL = get_app_config().orchestrator.base_url
except Exception:  # pragma: no cover - configuration loading failure
    _DEFAULT_ORCHESTRATOR_URL = "http://127.0.0.1:9000"

_PUBLIC_ORCH_BASE_URL = os.getenv("PUBLIC_ORCH_BASE_URL")
_ORCHESTRATOR_URL = (
    os.getenv("ORCHESTRATOR_BASE_URL")
    or _PUBLIC_ORCH_BASE_URL
    or _DEFAULT_ORCHESTRATOR_URL
)
_TELEMETRY_URL = os.getenv("TELEMETRY_BASE_URL", "http://127.0.0.1:8001")
_ORCHESTRATOR_TOKEN = os.getenv("ORCHESTRATOR_API_KEY")
_TELEMETRY_API_KEY = os.getenv("TELEMETRY_API_KEY")
_POLICY_BACKEND = os.getenv("POLICY_BACKEND", "ollama").strip().lower()
_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
_OLLAMA_AUTOSTART = parse_bool(os.getenv("OLLAMA_AUTOSTART"), default=True)

_REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _load_allowed_origins() -> list[str]:
    env_value = os.getenv("CONTROL_ALLOWED_ORIGINS", "")
    origins = set(_DEFAULT_ALLOWED_ORIGINS)
    if env_value.strip():
        for origin in env_value.split(","):
            origin = origin.strip()
            if origin:
                origins.add(origin)
    return sorted(origins)


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


def _fallback_metrics_snapshot(
    status: str, detail: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": status,
        "window_seconds": 0,
        "metrics": {},
    }
    if detail:
        payload["detail"] = detail
    return payload


async def _fetch_metrics_snapshot(gateway: ControlPanelGateway) -> Dict[str, Any]:
    try:
        metrics = await gateway.telemetry_get("/metrics/latest")
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        logger.warning(
            "Telemetry API returned %s for /metrics/latest: %s",
            exc.status_code,
            detail,
        )
        return _fallback_metrics_snapshot("error", detail)
    except httpx.HTTPError as exc:
        logger.warning(
            "Telemetry API unreachable for /metrics/latest: %s",
            exc,
        )
        return _fallback_metrics_snapshot("offline", str(exc))
    except Exception:
        logger.exception("Unexpected telemetry failure")
        return _fallback_metrics_snapshot("error", "Unexpected telemetry failure")
    if not isinstance(metrics, dict):
        logger.warning(
            "Telemetry API returned invalid payload type %s for /metrics/latest",
            type(metrics).__name__,
        )
        return _fallback_metrics_snapshot(
            "invalid_payload", "Telemetry payload malformed"
        )
    return metrics


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    gateway = ControlPanelGateway(_ORCHESTRATOR_URL, _TELEMETRY_URL)
    supervisor: Optional[OllamaSupervisor] = None
    if _POLICY_BACKEND == "ollama":
        supervisor = OllamaSupervisor(
            _OLLAMA_URL,
            autostart=_OLLAMA_AUTOSTART,
        )
        await supervisor.startup()
    app.state.ollama_supervisor = supervisor
    log_extra = {
        "orchestrator": _ORCHESTRATOR_URL,
        "telemetry": _TELEMETRY_URL,
        "policy_backend": _POLICY_BACKEND,
    }
    if supervisor is not None:
        log_extra["ollama_url"] = _OLLAMA_URL
        log_extra["ollama_autostart"] = supervisor.can_manage and _OLLAMA_AUTOSTART
    logger.info("Control backend ready", extra=log_extra)
    app.state.gateway = gateway
    try:
        yield
    finally:
        await gateway.close()
        stored_supervisor = getattr(app.state, "ollama_supervisor", None)
        if stored_supervisor is not None:
            await stored_supervisor.shutdown()


app = FastAPI(title="Kitsu Control Panel Backend", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_load_allowed_origins(),
    allow_origin_regex=r"https?://127\.0\.0\.1:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_gateway() -> ControlPanelGateway:
    gateway = getattr(app.state, "gateway", None)
    if gateway is None:
        raise RuntimeError("ControlPanelGateway not initialised")
    return gateway


async def get_supervisor() -> Optional[OllamaSupervisor]:
    supervisor = getattr(app.state, "ollama_supervisor", None)
    return supervisor


def require_supervisor(
    supervisor: Optional[OllamaSupervisor] = Depends(get_supervisor),
) -> OllamaSupervisor:
    if supervisor is None:
        raise HTTPException(
            status_code=400,
            detail="Policy backend does not use Ollama",
        )
    return supervisor


@app.get("/status", response_model=Dict[str, Any])
async def status(
    gateway: ControlPanelGateway = Depends(get_gateway),
    supervisor: Optional[OllamaSupervisor] = Depends(get_supervisor),
) -> Dict[str, Any]:
    orchestrator = await gateway.orchestrator_get("/status")
    metrics = await _fetch_metrics_snapshot(gateway)
    if supervisor is not None:
        ollama = await supervisor.status()
    else:
        ollama = {
            "backend": _POLICY_BACKEND,
            "status": "unmanaged",
            "autostart": False,
            "is_local": False,
        }
    return {"status": orchestrator, "metrics": metrics, "ollama": ollama}


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
        raise HTTPException(
            status_code=500, detail="Unexpected response from telemetry"
        )
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


@app.get("/llm/status", response_model=Dict[str, Any])
async def llm_status(
    supervisor: Optional[OllamaSupervisor] = Depends(get_supervisor),
) -> Dict[str, Any]:
    if supervisor is None:
        return {
            "backend": _POLICY_BACKEND,
            "status": "unmanaged",
            "autostart": False,
            "is_local": False,
        }
    return await supervisor.status()


@app.post("/llm/start", response_model=Dict[str, Any])
async def llm_start(
    supervisor: OllamaSupervisor = Depends(require_supervisor),
) -> Dict[str, Any]:
    if not supervisor.can_manage:
        raise HTTPException(
            status_code=400,
            detail="Ollama host is remote; please start it manually or disable autostart.",
        )
    await supervisor.ensure_started(force=True)
    return await supervisor.status()


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
