from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from libs.contracts import PersonaUpdateCommand

from ..deps import get_state, require_orchestrator_token
from ..state_manager import OrchestratorState

router = APIRouter()


@router.post("/persona", dependencies=[Depends(require_orchestrator_token)])
async def update_persona(
    payload: PersonaUpdateCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.update_persona(payload)
