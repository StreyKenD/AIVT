from __future__ import annotations

import asyncio
import html
import inspect
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, cast

import httpx
import yaml
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from libs.contracts import (
    ASRFinalEvent,
    ASREventPayload,
    ChatIngestCommand,
    ModuleToggleCommand,
    MuteCommand,
    OBSSceneCommand,
    PanicCommand,
    PersonaUpdateCommand,
    PresetCommand,
    TTSRequestPayload,
    VTSExpressionCommand,
)

try:  # pragma: no cover - fallback for environments without tenacity
    from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential
except (ImportError, ModuleNotFoundError):  # pragma: no cover - optional dependency
    from libs.compat.tenacity_shim import (
        AsyncRetrying,
        stop_after_attempt,
        wait_exponential,
    )

from libs.common import configure_json_logging
from libs.config import PersonaPreset, PersonaSettings, get_app_config
from libs.memory import MemoryController, MemorySummary
from libs.telemetry import TelemetryClient
from libs.telemetry.gpu import GPUMonitor


configure_json_logging("orchestrator")
logger = logging.getLogger(__name__)

settings = get_app_config()
orchestrator_cfg = settings.orchestrator
memory_cfg = settings.memory
persona_cfg = settings.persona
WEB_UI_ROOT = Path(__file__).resolve().parent / "webui"

POLICY_URL = orchestrator_cfg.policy_url
POLICY_TIMEOUT_SECONDS = orchestrator_cfg.policy_timeout_seconds
TTS_API_URL = orchestrator_cfg.tts_url
TTS_TIMEOUT_SECONDS = orchestrator_cfg.tts_timeout_seconds
_SPEECH_PATTERN = re.compile(r"<speech>(.*?)</speech>", re.IGNORECASE | re.DOTALL)

_policy_client: Optional[httpx.AsyncClient] = None
_tts_client: Optional[httpx.AsyncClient] = None


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


class ManualChatRequest(BaseModel):
    text: str = Field(..., min_length=1, description="User message to send to the AI.")
    play_tts: bool = Field(
        True,
        description="Whether the orchestrator should trigger TTS playback for the response.",
    )


class TelemetryPublisher:
    """Sends orchestrator events to an optional telemetry backend."""

    def __init__(
        self,
        base_url: Optional[str],
        *,
        api_key: Optional[str] = None,
        source: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._api_key = api_key
        self._source = source
        self._client: Optional[httpx.AsyncClient] = client
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
        timeout = httpx.Timeout(5.0)
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=timeout)

    async def shutdown(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    async def publish_event(self, event: Dict[str, Any]) -> None:
        if self._client is None:
            return
        headers: Dict[str, str] = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key
        body = dict(event)
        if self._source and not body.get("source"):
            body["source"] = self._source
        body.setdefault("ts", time.time())
        request_kwargs: Dict[str, Any] = {"json": body}
        if headers:
            signature = inspect.signature(self._client.post)
            accepts_headers = any(
                param.kind is inspect.Parameter.VAR_KEYWORD or name == "headers"
                for name, param in signature.parameters.items()
            )
            if accepts_headers:
                request_kwargs["headers"] = headers
        try:
            async for attempt in self._retry_factory():
                with attempt:
                    await self._client.post("/events", **request_kwargs)
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
        source = message.get("source")
        if isinstance(source, str) and source:
            telemetry_payload["source"] = source
        try:
            await self._telemetry.publish_event(telemetry_payload)
        except Exception:  # pragma: no cover - defensive guard
            logger.exception("Telemetry publish raised unexpectedly")


class OrchestratorState:
    """Holds runtime state for the orchestrator and synthesizes status payloads."""

    def __init__(
        self,
        broker: EventBroker,
        memory: MemoryController,
        persona_presets: Dict[str, PersonaPreset],
        default_preset: str,
    ) -> None:
        self._persona_presets = persona_presets
        self.available_presets = sorted(self._persona_presets.keys())
        if default_preset not in self._persona_presets:
            if self.available_presets:
                default_preset = self.available_presets[0]
            else:
                fallback = PersonaPreset()
                self._persona_presets = {"default": fallback}
                self.available_presets = ["default"]
                default_preset = "default"
        base_preset = self._persona_presets[default_preset]
        self.persona = PersonaState(
            style=base_preset.style,
            chaos_level=base_preset.chaos_level,
            energy=base_preset.energy,
            family_mode=base_preset.family_mode,
        )
        self._persona_prompts = {
            name: preset.system_prompt
            for name, preset in self._persona_presets.items()
            if preset.system_prompt
        }
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
        self.active_preset = default_preset

    def snapshot(self) -> Dict[str, Any]:
        return {
            "status": "ok",
            "persona": self.persona.snapshot(),
            "persona_presets": {
                "active": self.active_preset,
                "available": self.available_presets,
            },
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
            if module == "tts_worker":
                self.tts_muted = not enabled
            payload = {"type": "module.toggle", "module": module, "enabled": enabled}
        await self._broker.publish(payload)
        return payload

    def _resolve_preset(self, name: str) -> PersonaPreset:
        try:
            return self._persona_presets[name]
        except KeyError as exc:  # pragma: no cover - defensive guard
            available = ", ".join(self.available_presets) or "<none>"
            raise ValueError(f"Unknown preset: {name}. Available: {available}") from exc

    async def _apply_persona_update(
        self,
        payload: PersonaUpdateCommand,
        *,
        preset_name: Optional[str],
        announce: bool = True,
        log_turn: bool = True,
    ) -> Dict[str, Any]:
        async with self._lock:
            self.persona.update(
                style=payload.style,
                chaos_level=payload.chaos_level,
                energy=payload.energy,
                family_mode=payload.family_mode,
            )
            if preset_name is not None:
                self.active_preset = preset_name
            elif any(
                value is not None
                for value in (
                    payload.style,
                    payload.chaos_level,
                    payload.energy,
                    payload.family_mode,
                )
            ):
                self.active_preset = "custom"
            snapshot = {
                "type": "persona_update",
                "persona": self.persona.snapshot(),
                "active_preset": self.active_preset,
            }
        if announce:
            await self._broker.publish(snapshot)
        if log_turn:
            await self.record_turn(
                "system",
                f"Persona updated to {self.persona.style} (chaos={self.persona.chaos_level:.2f})",
            )
        return snapshot

    async def update_persona(self, payload: PersonaUpdateCommand) -> Dict[str, Any]:
        if payload.preset:
            return await self.apply_preset(payload.preset)
        return await self._apply_persona_update(payload, preset_name=None)

    async def record_tts(self, request: TTSRequestPayload) -> Dict[str, Any]:
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

    def _mark_module_latency(self, module: str, latency_ms: float) -> None:
        state = self.modules.get(module)
        if state is None:
            return
        state.latency_ms = max(1.0, float(latency_ms))
        state.last_updated = time.time()

    async def handle_asr_final(self, event: ASREventPayload) -> None:
        if event.type != "asr_final":
            return
        final_event = cast(ASRFinalEvent, event)
        text = final_event.text.strip()
        if not text:
            return
        try:
            await self._process_asr_final(text, final_event)
        except Exception:  # pragma: no cover - defensive guard
            logger.exception("Failed to process ASR final payload")

    async def _process_asr_final(self, text: str, _event: ASRFinalEvent) -> None:
        await self.record_turn("user", text)
        await self._run_policy_pipeline(text, synthesize=not self.tts_muted)

    async def process_manual_prompt(
        self, text: str, *, synthesize: bool = True
    ) -> Optional[Dict[str, Any]]:
        clean = text.strip()
        if not clean:
            return None
        await self.record_turn("user", clean)
        return await self._run_policy_pipeline(clean, synthesize=synthesize)

    async def _run_policy_pipeline(
        self, text: str, *, synthesize: bool = True
    ) -> Optional[Dict[str, Any]]:
        request_body = self._build_policy_request(text)
        start = time.perf_counter()
        final_payload = await _invoke_policy(request_body, self._broker)
        latency_ms = (time.perf_counter() - start) * 1000
        self._mark_module_latency("policy_worker", latency_ms)
        if final_payload is None:
            logger.warning("Policy worker returned no final payload for request")
            return None

        await self._broker.publish({"type": "policy.final", "payload": final_payload})

        speech_content = _extract_speech(final_payload.get("content", ""))
        if not speech_content:
            speech_content = (final_payload.get("content") or "").strip()
        if not speech_content:
            return final_payload

        if not synthesize or self.tts_muted:
            await self.record_turn("assistant", speech_content)
            return final_payload

        tts_start = time.perf_counter()
        tts_result = await _invoke_tts(
            speech_content,
            final_payload.get("meta", {}).get("voice"),
            final_payload.get("request_id"),
        )
        tts_latency_ms = (time.perf_counter() - tts_start) * 1000
        self._mark_module_latency("tts_worker", tts_latency_ms)
        if tts_result is not None:
            await self._broker.publish({"type": "tts.generated", "payload": tts_result})
        voice_hint = None
        if isinstance(tts_result, dict):
            voice_hint = tts_result.get("voice")
        await self.record_tts(
            TTSRequestPayload(text=speech_content, voice=voice_hint)
        )
        return final_payload

    def _build_policy_request(self, text: str) -> Dict[str, Any]:
        persona = self.persona.snapshot()
        payload: Dict[str, Any] = {
            "text": text,
            "persona_style": persona["style"],
            "chaos_level": persona["chaos_level"],
            "energy": persona["energy"],
            "family_friendly": persona["family_mode"],
        }
        persona_prompt = self._persona_prompts.get(self.active_preset)
        if persona_prompt:
            payload["persona_prompt"] = persona_prompt
        if self.last_summary:
            payload["memory_summary"] = self.last_summary.summary_text
        recent_turns = [
            {"role": turn.role, "content": turn.text}
            for turn in self.memory.buffer.as_list()[-6:]
        ]
        if recent_turns:
            payload["recent_turns"] = recent_turns
        return payload

    async def update_scene(self, scene: str) -> Dict[str, Any]:
        async with self._lock:
            self.current_scene = scene
            payload = {"type": "obs_scene", "scene": scene, "ts": time.time()}
        await self._broker.publish(payload)
        return payload

    async def update_expression(
        self, expression: VTSExpressionCommand
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
        config = self._resolve_preset(preset)
        persona_update = PersonaUpdateCommand(
            style=config.style,
            chaos_level=config.chaos_level,
            energy=config.energy,
            family_mode=config.family_mode,
        )
        await self._apply_persona_update(
            persona_update, preset_name=preset, announce=True
        )
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


async def _invoke_policy(
    payload: Dict[str, Any], broker: EventBroker
) -> Optional[Dict[str, Any]]:
    if _policy_client is None:
        logger.warning("Policy client is not initialised; skipping LLM request")
        return None
    final_event: Optional[Dict[str, Any]] = None
    current_event: Optional[str] = None
    try:
        async with _policy_client.stream("POST", "/respond", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    current_event = None
                    continue
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                    continue
                if line.startswith("data:"):
                    data_line = line.split(":", 1)[1].strip()
                    if not data_line:
                        continue
                    try:
                        data = json.loads(data_line)
                    except json.JSONDecodeError:
                        logger.debug("Discarding non-JSON SSE chunk: %s", data_line)
                        continue
                    if current_event == "token":
                        await broker.publish({"type": "policy.token", "payload": data})
                    elif current_event == "final":
                        final_event = data
    except Exception:  # pragma: no cover - network guard
        logger.exception("Policy worker request failed")
        return None
    return final_event


async def _invoke_tts(
    text: str, voice: Optional[str], request_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    if _tts_client is None:
        logger.warning("TTS client is not initialised; skipping speech synthesis")
        return None
    payload: Dict[str, Any] = {"text": text}
    if voice:
        payload["voice"] = voice
    if request_id:
        payload["request_id"] = request_id
    try:
        response = await _tts_client.post("/speak", json=payload)
        response.raise_for_status()
        return response.json()
    except Exception:  # pragma: no cover - network guard
        logger.exception("TTS worker request failed")
        return None


def _extract_speech(content: Optional[str]) -> str:
    if not content:
        return ""
    match = _SPEECH_PATTERN.search(content)
    if not match:
        return ""
    value = html.unescape(match.group(1))
    return value.strip()


def _load_web_asset(filename: str) -> str:
    path = WEB_UI_ROOT / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - defensive guard
        logger.error("Failed to read web asset %s: %s", path, exc)
        raise HTTPException(status_code=500, detail="Unable to load asset") from exc


def _load_persona_presets(config: PersonaSettings) -> Dict[str, PersonaPreset]:
    presets: Dict[str, PersonaPreset] = {}
    for name, preset in config.presets.items():
        if isinstance(preset, PersonaPreset):
            presets[name] = preset
        else:
            presets[name] = PersonaPreset.model_validate(preset)
    if config.presets_file:
        preset_path = Path(config.presets_file).expanduser()
        try:
            raw = preset_path.read_text(encoding="utf-8")
            loaded = yaml.safe_load(raw) or {}
            if isinstance(loaded, dict):
                for name, values in loaded.items():
                    try:
                        presets[name] = PersonaPreset.model_validate(values)
                    except Exception as exc:  # pragma: no cover - defensive guard
                        logger.warning("Skipping persona preset %s: %s", name, exc)
        except FileNotFoundError:
            logger.warning("Persona presets file %s not found", preset_path)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning(
                "Failed to load persona presets file %s: %s", preset_path, exc
            )
    return presets


memory_controller = MemoryController(
    buffer_size=memory_cfg.buffer_size,
    summary_interval=memory_cfg.summary_interval,
    history_path=Path(memory_cfg.history_path).expanduser(),
)
telemetry = TelemetryPublisher(
    orchestrator_cfg.telemetry_url,
    api_key=orchestrator_cfg.telemetry_api_key,
    source="orchestrator",
)
broker = EventBroker(telemetry)
persona_presets = _load_persona_presets(persona_cfg)
state = OrchestratorState(
    broker,
    memory_controller,
    persona_presets=persona_presets,
    default_preset=persona_cfg.default,
)
gpu_telemetry = (
    TelemetryClient(
        orchestrator_cfg.telemetry_url,
        api_key=orchestrator_cfg.telemetry_api_key,
        service="orchestrator.gpu",
    )
    if orchestrator_cfg.telemetry_url
    else None
)
gpu_monitor = GPUMonitor(
    gpu_telemetry,
    interval_seconds=orchestrator_cfg.gpu_metrics_interval_seconds,
)
app = FastAPI(title="Kitsu Orchestrator", version="0.2.0")


@app.on_event("startup")
async def on_startup() -> None:
    global _policy_client, _tts_client
    restore_flag = memory_cfg.restore_context
    restore_window = memory_cfg.restore_window_seconds
    await telemetry.startup()
    if _policy_client is None:
        _policy_client = httpx.AsyncClient(
            base_url=POLICY_URL,
            timeout=httpx.Timeout(POLICY_TIMEOUT_SECONDS),
        )
    if _tts_client is None:
        _tts_client = httpx.AsyncClient(
            base_url=TTS_API_URL,
            timeout=httpx.Timeout(TTS_TIMEOUT_SECONDS),
        )
    await state.startup(restore_flag, restore_window)
    state.start_background_tasks()
    await gpu_monitor.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _policy_client, _tts_client
    await state.shutdown()
    await telemetry.shutdown()
    await gpu_monitor.stop()
    if _policy_client is not None:
        await _policy_client.aclose()
        _policy_client = None
    if _tts_client is not None:
        await _tts_client.aclose()
        _tts_client = None


async def get_state() -> OrchestratorState:
    return state


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/status")
async def get_status(
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return orchestrator.snapshot()


@app.post("/toggle/{module}")
async def toggle_module(
    module: str,
    payload: ModuleToggleCommand,
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
    payload: PersonaUpdateCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.update_persona(payload)


@app.post("/tts")
async def request_tts(
    payload: TTSRequestPayload,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.record_tts(payload)


@app.post("/obs/scene")
async def set_obs_scene(
    payload: OBSSceneCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.update_scene(payload.scene)


@app.post("/vts/expr")
async def set_vts_expression(
    payload: VTSExpressionCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.update_expression(payload)


@app.post("/ingest/chat")
async def ingest_chat(
    payload: ChatIngestCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    summary_payload = await orchestrator.record_turn(payload.role, payload.text)
    return {
        "status": "accepted",
        "summary_generated": summary_payload is not None,
    }


@app.post("/chat/respond")
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


@app.get("/webui/chat", response_class=HTMLResponse)
async def chat_console() -> HTMLResponse:
    return HTMLResponse(_load_web_asset("chat.html"))


@app.get("/webui/overlay", response_class=HTMLResponse)
async def overlay_page() -> HTMLResponse:
    return HTMLResponse(_load_web_asset("overlay.html"))


@app.post("/events/asr")
async def receive_asr_event(
    payload: ASREventPayload,
    orchestrator: OrchestratorState = Depends(get_state),
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


@app.post("/control/panic")
async def trigger_panic(
    payload: PanicCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.trigger_panic(payload.reason)


@app.post("/control/mute")
async def toggle_mute(
    payload: MuteCommand,
    orchestrator: OrchestratorState = Depends(get_state),
) -> Dict[str, Any]:
    return await orchestrator.set_mute(payload.muted)


@app.post("/control/preset")
async def apply_preset(
    payload: PresetCommand,
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
