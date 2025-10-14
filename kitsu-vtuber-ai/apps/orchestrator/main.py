from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, validator
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

from libs.common import configure_json_logging
from libs.memory import MemoryController, MemorySummary
from libs.telemetry import TelemetryClient
from libs.telemetry.gpu import GPUMonitor


configure_json_logging("orchestrator")
logger = logging.getLogger(__name__)


@dataclass
class ModuleState:
    """Represents the lifecycle of a subsystem handled by the orchestrator."""

    name: str
    enabled: bool = True
    latency_ms: float = field(default_factory=lambda: random.uniform(15, 50))
    last_updated: float = field(default_factory=time.time)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "state": "online" if self.enabled else "offline",
            "latency_ms": round(self.latency_ms, 2),
            "last_updated": self.last_updated,
        }

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.last_updated = time.time()

    def jitter(self) -> None:
        """Simulate latency jitter for dashboards."""
        delta = random.uniform(-5, 5)
        self.latency_ms = max(1.0, self.latency_ms + delta)
        self.last_updated = time.time()


@dataclass
class PersonaState:
    style: str = "kawaii"
    chaos_level: float = 0.2
    energy: float = 0.5
    family_mode: bool = True
    last_updated: float = field(default_factory=time.time)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "style": self.style,
            "chaos_level": self.chaos_level,
            "energy": self.energy,
            "family_mode": self.family_mode,
            "last_updated": self.last_updated,
        }

    def update(
        self,
        *,
        style: Optional[str] = None,
        chaos_level: Optional[float] = None,
        energy: Optional[float] = None,
        family_mode: Optional[bool] = None,
    ) -> None:
        if style is not None:
            self.style = style
        if chaos_level is not None:
            self.chaos_level = chaos_level
        if energy is not None:
            self.energy = energy
        if family_mode is not None:
            self.family_mode = family_mode
        self.last_updated = time.time()


class PersonaUpdate(BaseModel):
    style: Optional[str] = Field(
        None, description="Persona style, e.g. kawaii or chaotic"
    )
    chaos_level: Optional[float] = Field(None, ge=0.0, le=1.0)
    energy: Optional[float] = Field(None, ge=0.0, le=1.0)
    family_mode: Optional[bool] = Field(
        None, description="Family friendly moderation flag"
    )

    @validator("style")
    def validate_style(cls, value: Optional[str]) -> Optional[str]:  # noqa: D417
        if value is None:
            return value
        allowed = {"kawaii", "chaotic", "calm"}
        if value not in allowed:
            raise ValueError(f"Unsupported persona style: {value}")
        return value


class ModuleToggleRequest(BaseModel):
    enabled: bool


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice: Optional[str] = Field(None, description="Preferred voice identifier")


class OBSSceneRequest(BaseModel):
    scene: str = Field(..., min_length=1)


class VTSExpressionRequest(BaseModel):
    expression: str = Field(..., min_length=1)
    intensity: Optional[float] = Field(0.6, ge=0.0, le=1.0)


class ChatIngestRequest(BaseModel):
    role: str = Field("user", description="speaker role: user|assistant|system")
    text: str = Field(..., min_length=1)

    @validator("role")
    def validate_role(cls, value: str) -> str:  # noqa: D417
        allowed = {"user", "assistant", "system"}
        if value not in allowed:
            raise ValueError("Invalid role")
        return value


class ASREvent(BaseModel):
    type: Literal["asr_partial", "asr_final"]
    segment: int = Field(..., ge=0)
    text: str = Field(..., min_length=1)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    language: Optional[str] = Field(None, min_length=1)
    started_at: float = Field(..., ge=0.0)
    ended_at: float = Field(..., ge=0.0)
    latency_ms: Optional[float] = Field(None, ge=0.0)
    duration_ms: Optional[float] = Field(None, ge=0.0)

    @validator("ended_at")
    def validate_timestamps(
        cls, value: float, values: Dict[str, Any]
    ) -> float:  # noqa: D417
        started_at = values.get("started_at")
        if started_at is not None and value < started_at:
            raise ValueError("ended_at must be greater than or equal to started_at")
        return value


class PanicRequest(BaseModel):
    reason: Optional[str] = Field(
        None,
        description="Motivo opcional para o gatilho de pânico",
        max_length=240,
    )


class MuteRequest(BaseModel):
    muted: bool = Field(..., description="Define se o TTS deve permanecer mudo")


class PresetRequest(BaseModel):
    preset: str = Field(..., min_length=1, description="Identificador do preset")

    @validator("preset")
    def validate_preset(cls, value: str) -> str:  # noqa: D417
        allowed = set(OrchestratorState._PRESETS.keys())  # type: ignore[attr-defined]
        if value not in allowed:
            raise ValueError(f"Preset desconhecido: {value}")
        return value


class TelemetryPublisher:
    """Sends orchestrator events to an optional telemetry backend."""

    def __init__(self, base_url: Optional[str]) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._client: Optional[httpx.AsyncClient] = None
        self._retry_factory: Callable[[], AsyncRetrying] = self._default_retry_factory

    def _default_retry_factory(self) -> AsyncRetrying:
        return AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4.0),
            reraise=True,
        )

    async def startup(self) -> None:
        if self._base_url is None or self._client is not None:
            return
        self._client = httpx.AsyncClient(
            base_url=self._base_url, timeout=httpx.Timeout(5.0)
        )

    async def shutdown(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    async def publish_event(self, event: Dict[str, Any]) -> None:
        if self._client is None:
            return
        try:
            async for attempt in self._retry_factory():
                with attempt:
                    await self._client.post("/events", json=event)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning(
                "Telemetry publish failed for %s: %s",
                event.get("type"),
                exc,
                exc_info=True,
            )


class EventBroker:
    """Simple pub/sub broker for broadcasting orchestrator events over WebSocket."""

    def __init__(self, telemetry: Optional[TelemetryPublisher] = None) -> None:
        self._subscribers: Dict[int, asyncio.Queue[Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._counter = 0
        self._telemetry = telemetry

    async def subscribe(self) -> tuple[int, asyncio.Queue[Dict[str, Any]]]:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        async with self._lock:
            token = self._counter
            self._counter += 1
            self._subscribers[token] = queue
        return token, queue

    async def unsubscribe(self, token: int) -> None:
        async with self._lock:
            self._subscribers.pop(token, None)

    async def publish(self, message: Dict[str, Any]) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.values())
        for queue in subscribers:
            await queue.put(message)
        if self._telemetry is None:
            return
        event_type = message.get("type", "unknown")
        event_payload = message.get("payload")
        if event_payload is None:
            event_payload = {
                key: value for key, value in message.items() if key != "type"
            }
        telemetry_payload = {
            "type": event_type,
            "ts": time.time(),
            "payload": event_payload,
        }
        try:
            await self._telemetry.publish_event(telemetry_payload)
        except Exception:  # pragma: no cover - defensive guard
            logger.exception("Telemetry publish raised unexpectedly")


class OrchestratorState:
    """Holds runtime state for the orchestrator and synthesizes status payloads."""

    _PRESETS: Dict[str, Dict[str, Any]] = {
        "default": {
            "style": "kawaii",
            "chaos_level": 0.2,
            "energy": 0.5,
            "family_mode": True,
        },
        "cozy": {
            "style": "calm",
            "chaos_level": 0.15,
            "energy": 0.35,
            "family_mode": True,
        },
        "hype": {
            "style": "chaotic",
            "chaos_level": 0.75,
            "energy": 0.85,
            "family_mode": True,
        },
    }

    def __init__(self, broker: EventBroker, memory: MemoryController) -> None:
        self.persona = PersonaState()
        self.modules: Dict[str, ModuleState] = {
            module: ModuleState(module)
            for module in (
                "asr_worker",
                "policy_worker",
                "tts_worker",
                "avatar_controller",
                "obs_controller",
                "twitch_ingest",
            )
        }
        self.current_scene: str = "Starting Soon"
        self.last_expression: Dict[str, Any] = {"expression": "smile", "intensity": 0.5}
        self.last_tts_request: Optional[Dict[str, Any]] = None
        self._broker = broker
        self.memory = memory
        self._tasks: List[asyncio.Task[Any]] = []
        self._lock = asyncio.Lock()
        self.restore_context = False
        self.last_summary: Optional[MemorySummary] = None
        self.tts_muted = False
        self.panic_triggered_at: Optional[float] = None
        self.panic_reason: Optional[str] = None
        self.active_preset = "default"

    def snapshot(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "persona": self.persona.snapshot(),
            "modules": {
                name: module.snapshot() for name, module in self.modules.items()
            },
            "scene": self.current_scene,
            "last_expression": self.last_expression,
            "last_tts": self.last_tts_request,
            "memory": self.memory.snapshot(),
            "restore_context": self.restore_context,
            "control": {
                "tts_muted": self.tts_muted,
                "panic_at": self.panic_triggered_at,
                "panic_reason": self.panic_reason,
                "active_preset": self.active_preset,
            },
        }

    async def startup(self, restore: bool, restore_window: float) -> None:
        self.restore_context = restore
        summary = await self.memory.prepare(restore, restore_window)
        self.last_summary = summary
        if summary:
            await self._broker.publish(
                {"type": "memory_summary", "summary": summary.to_dict()}
            )

    async def toggle_module(self, module: str, enabled: bool) -> Dict[str, Any]:
        if module not in self.modules:
            raise KeyError(module)
        async with self._lock:
            self.modules[module].set_enabled(enabled)
            payload = {"type": "module.toggle", "module": module, "enabled": enabled}
        await self._broker.publish(payload)
        return payload

    async def update_persona(self, payload: PersonaUpdate) -> Dict[str, Any]:
        async with self._lock:
            self.persona.update(
                style=payload.style,
                chaos_level=payload.chaos_level,
                energy=payload.energy,
                family_mode=payload.family_mode,
            )
            snapshot = {"type": "persona_update", "persona": self.persona.snapshot()}
        await self._broker.publish(snapshot)
        await self.record_turn(
            "system",
            f"Persona updated to {self.persona.style} (chaos={self.persona.chaos_level:.2f})",
        )
        return snapshot

    async def record_tts(self, request: TTSRequest) -> Dict[str, Any]:
        async with self._lock:
            self.last_tts_request = {
                "text": request.text,
                "voice": request.voice,
                "ts": time.time(),
            }
            payload: Dict[str, Any] = {
                "type": "tts_request",
                "data": self.last_tts_request,
            }
        await self._broker.publish(payload)
        summary_payload = await self.record_turn("assistant", request.text)
        payload["summary_generated"] = summary_payload is not None
        return payload

    async def update_scene(self, scene: str) -> Dict[str, Any]:
        async with self._lock:
            self.current_scene = scene
            payload = {"type": "obs_scene", "scene": scene, "ts": time.time()}
        await self._broker.publish(payload)
        return payload

    async def update_expression(
        self, expression: VTSExpressionRequest
    ) -> Dict[str, Any]:
        async with self._lock:
            self.last_expression = {
                "expression": expression.expression,
                "intensity": expression.intensity,
                "ts": time.time(),
            }
            payload = {"type": "vts_expression", "data": self.last_expression}
        await self._broker.publish(payload)
        return payload

    async def record_turn(self, role: str, text: str) -> Optional[Dict[str, Any]]:
        summary = await self.memory.add_turn(role, text)
        if summary is None:
            return None
        self.last_summary = summary
        payload = {"type": "memory_summary", "summary": summary.to_dict()}
        await self._broker.publish(payload)
        return payload

    async def trigger_panic(self, reason: Optional[str]) -> Dict[str, Any]:
        async with self._lock:
            self.panic_triggered_at = time.time()
            self.panic_reason = reason or None
            payload = {
                "type": "control.panic",
                "ts": self.panic_triggered_at,
            }
            if self.panic_reason:
                payload["reason"] = self.panic_reason
        await self._broker.publish(payload)
        return payload

    async def set_mute(self, muted: bool) -> Dict[str, Any]:
        async with self._lock:
            self.tts_muted = muted
            payload = {
                "type": "control.mute",
                "muted": muted,
                "ts": time.time(),
            }
        await self._broker.publish(payload)
        await self.toggle_module("tts_worker", enabled=not muted)
        return payload

    async def apply_preset(self, preset: str) -> Dict[str, Any]:
        try:
            config = self._PRESETS[preset]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise ValueError(f"Unknown preset: {preset}") from exc

        persona_update = PersonaUpdate(
            style=config["style"],
            chaos_level=config["chaos_level"],
            energy=config["energy"],
            family_mode=config.get("family_mode"),
        )
        await self.update_persona(persona_update)
        async with self._lock:
            self.active_preset = preset
            payload = {
                "type": "control.preset",
                "preset": preset,
                "ts": time.time(),
            }
        await self._broker.publish(payload)
        return payload

    def start_background_tasks(self) -> None:
        self._tasks.append(asyncio.create_task(self._simulate_latency()))

    async def shutdown(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _simulate_latency(self) -> None:
        while True:
            await asyncio.sleep(5)
            async with self._lock:
                for module in self.modules.values():
                    module.jitter()
                snapshot = {"type": "status", "payload": self.snapshot()}
            await self._broker.publish(snapshot)


memory_controller = MemoryController()
telemetry = TelemetryPublisher(os.getenv("TELEMETRY_API_URL"))
broker = EventBroker(telemetry)
state = OrchestratorState(broker, memory_controller)
gpu_monitor = GPUMonitor(
    TelemetryClient.from_env(service="orchestrator.gpu"),
    interval_seconds=float(os.getenv("GPU_METRICS_INTERVAL_SECONDS", "30")),
)
app = FastAPI(title="Kitsu Orchestrator", version="0.2.0")


@app.on_event("startup")
async def on_startup() -> None:
    restore_flag = os.getenv("RESTORE_CONTEXT", "false").lower() in {"1", "true", "yes"}
    restore_window = float(os.getenv("MEMORY_RESTORE_WINDOW_SECONDS", "7200"))
    await telemetry.startup()
    await state.startup(restore_flag, restore_window)
    state.start_background_tasks()
    await gpu_monitor.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await state.shutdown()
    await telemetry.shutdown()
    await gpu_monitor.stop()


async def get_state() -> OrchestratorState:
    return state


@app.get("/status")
async def get_status(
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return orchestrator.snapshot()


@app.post("/toggle/{module}")
async def toggle_module(
    module: str,
    payload: ModuleToggleRequest,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    try:
        return await orchestrator.toggle_module(module, payload.enabled)
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise HTTPException(
            status_code=404, detail=f"Unknown module: {module}"
        ) from exc


@app.post("/persona")
async def update_persona(
    payload: PersonaUpdate,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.update_persona(payload)


@app.post("/tts")
async def request_tts(
    payload: TTSRequest,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.record_tts(payload)


@app.post("/obs/scene")
async def set_obs_scene(
    payload: OBSSceneRequest,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.update_scene(payload.scene)


@app.post("/vts/expr")
async def set_vts_expression(
    payload: VTSExpressionRequest,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.update_expression(payload)


@app.post("/ingest/chat")
async def ingest_chat(
    payload: ChatIngestRequest,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    summary_payload = await orchestrator.record_turn(payload.role, payload.text)
    return {
        "status": "accepted",
        "summary_generated": summary_payload is not None,
    }


@app.post("/events/asr")
async def receive_asr_event(
    payload: ASREvent,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    body = payload.dict()
    event_type = body.pop("type")
    message = {"type": event_type, "payload": body}
    await broker.publish(message)
    module = orchestrator.modules.get("asr_worker")
    if module is not None:
        metric = body.get("latency_ms") or body.get("duration_ms")
        if metric is not None:
            module.latency_ms = max(1.0, float(metric))
        module.last_updated = time.time()
    return {"status": "accepted"}


@app.post("/control/panic")
async def trigger_panic(
    payload: PanicRequest,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.trigger_panic(payload.reason)


@app.post("/control/mute")
async def toggle_mute(
    payload: MuteRequest,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.set_mute(payload.muted)


@app.post("/control/preset")
async def apply_preset(
    payload: PresetRequest,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    try:
        return await orchestrator.apply_preset(payload.preset)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.websocket("/stream")
async def stream_events(websocket: WebSocket) -> None:
    await websocket.accept()
    token, queue = await broker.subscribe()
    try:
        await websocket.send_json({"type": "status", "payload": state.snapshot()})
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        await broker.unsubscribe(token)
