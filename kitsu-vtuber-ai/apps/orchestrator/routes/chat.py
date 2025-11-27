from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from libs.contracts import ChatIngestCommand

from ..deps import get_state, require_orchestrator_token
from ..schemas import ManualChatRequest
from ..state_manager import OrchestratorState

router = APIRouter()


@router.post("/ingest/chat", dependencies=[Depends(require_orchestrator_token)])
async def ingest_chat(
    payload: ChatIngestCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    summary_payload = await orchestrator.record_turn(payload.role, payload.text)
    return {
        "status": "accepted",
        "summary_generated": summary_payload is not None,
    }


@router.post("/chat/respond", dependencies=[Depends(require_orchestrator_token)])
async def respond_via_chat(
    payload: ManualChatRequest,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    result = await orchestrator.process_manual_prompt(
        payload.text, synthesize=payload.play_tts
    )
    if result is None:
        raise HTTPException(status_code=202, detail="No response generated yet")
    return {"status": "ok", "payload": result}
