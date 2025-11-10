from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from libs.contracts import TTSRequestPayload

from ..deps import get_state, require_orchestrator_token
from ..state import OrchestratorState

router = APIRouter()


@router.post("/tts", dependencies=[Depends(require_orchestrator_token)])
async def request_tts(
    payload: TTSRequestPayload,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.record_tts(payload)
