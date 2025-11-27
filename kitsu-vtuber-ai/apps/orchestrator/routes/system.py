from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from libs.contracts import ModuleToggleCommand

from ..deps import get_state, require_orchestrator_token
from ..metrics import render_prometheus
from ..state_manager import OrchestratorState

router = APIRouter()


@router.get("/health")
async def health(orchestrator: OrchestratorState = Depends(get_state)) -> Dict[str, Any]:
    """Return a snapshot with module health, uptime, and panic/mute flags."""
    return orchestrator.health_snapshot()


@router.get("/status")
async def get_status(
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    """Return the full orchestrator status payload consumed by the UI."""
    return orchestrator.snapshot()


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
)
async def metrics() -> PlainTextResponse:
    """Expose Prometheus-formatted metrics for scraper targets."""
    payload = render_prometheus()
    return PlainTextResponse(payload, media_type="text/plain; version=0.0.4")


@router.post("/toggle/{module}", dependencies=[Depends(require_orchestrator_token)])
async def toggle_module(
    module: str,
    payload: ModuleToggleCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    """Enable/disable a worker module and broadcast the change."""
    try:
        return await orchestrator.toggle_module(module, payload.enabled)
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(
            status_code=404, detail=f"Unknown module: {module}"
        ) from exc
