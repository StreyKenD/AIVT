from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from libs.contracts import PersonaUpdateCommand

from ..deps import get_state
from ..state import OrchestratorState

router = APIRouter()


@router.post("/persona")
async def update_persona(
    payload: PersonaUpdateCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.update_persona(payload)
