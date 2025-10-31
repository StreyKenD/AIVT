from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from libs.contracts import OBSSceneCommand, VTSExpressionCommand

from ..deps import get_state
from ..state import OrchestratorState

router = APIRouter()


@router.post("/obs/scene")
async def set_obs_scene(
    payload: OBSSceneCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.update_scene(payload.scene)


@router.post("/vts/expr")
async def set_vts_expression(
    payload: VTSExpressionCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.update_expression(payload)
