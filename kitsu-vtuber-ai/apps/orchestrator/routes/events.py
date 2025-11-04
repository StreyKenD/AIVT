from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from libs.contracts import ASREventPayload

from ..broker import EventBroker
from ..deps import get_broker, get_state
from ..state import OrchestratorState

router = APIRouter()


@router.post("/events/asr")
async def receive_asr_event(
    payload: ASREventPayload,
    orchestrator: OrchestratorState = Depends(get_state),
    broker: EventBroker = Depends(get_broker),
) -> Dict[str, Any]:
    body = payload.dict()
    event_type = payload.type
    body.pop("type", None)
    message = {"type": event_type, "payload": body}
    await broker.publish(message)
    module = orchestrator.modules.get("asr_worker")
    if module is not None:
        metric = body.get("latency_ms") or body.get("duration_ms")
        if metric is not None:
            module.latency_ms = max(1.0, float(metric))
        module.last_updated = time.time()
    if event_type == "asr_final":
        asyncio.create_task(orchestrator.handle_asr_final(payload))
    return {"status": "accepted"}


@router.websocket("/stream")
async def stream_events(
    websocket: WebSocket,
    broker: EventBroker = Depends(get_broker),
    orchestrator: OrchestratorState = Depends(get_state),
) -> None:
    await websocket.accept()
    token, queue = await broker.subscribe()
    try:
        await websocket.send_json(
            {"type": "status", "payload": orchestrator.snapshot()}
        )
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        await broker.unsubscribe(token)
