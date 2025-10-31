from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from libs.contracts import MuteCommand, PanicCommand, PresetCommand

from ..deps import get_state
from ..state import OrchestratorState

router = APIRouter()


@router.post("/control/panic")
async def trigger_panic(
    payload: PanicCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.trigger_panic(payload.reason)


@router.post("/control/mute")
async def toggle_mute(
    payload: MuteCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.set_mute(payload.muted)


@router.post("/control/preset")
async def apply_preset(
    payload: PresetCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    try:
        return await orchestrator.apply_preset(payload.preset)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
