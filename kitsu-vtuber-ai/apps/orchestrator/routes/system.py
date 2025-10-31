from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from libs.contracts import ModuleToggleCommand

from ..deps import get_state
from ..state import OrchestratorState

router = APIRouter()


@router.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@router.get("/status")
async def get_status(
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return orchestrator.snapshot()


@router.post("/toggle/{module}")
async def toggle_module(
    module: str,
    payload: ModuleToggleCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    try:
        return await orchestrator.toggle_module(module, payload.enabled)
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(status_code=404, detail=f"Unknown module: {module}") from exc
