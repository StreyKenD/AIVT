from __future__ import annotations

import asyncio
import html
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, cast

from libs.config import PersonaPreset
from libs.contracts import (
    ASRFinalEvent,
    ASREventPayload,
    PersonaUpdateCommand,
    TTSRequestPayload,
    VTSExpressionCommand,
)
from libs.memory import MemoryController, MemorySummary

from .broker import EventBroker

logger = logging.getLogger(__name__)

_SPEECH_PATTERN = re.compile(r"<speech>(.*?)</speech>", re.IGNORECASE | re.DOTALL)

PolicyInvoker = Callable[
    [Dict[str, Any], EventBroker], Awaitable[Optional[Dict[str, Any]]]
]
TTSInvoker = Callable[
    [str, Optional[str], Optional[str]], Awaitable[Optional[Dict[str, Any]]]
]


@dataclass
class ModuleState:
    """Represents the lifecycle of a subsystem handled by the orchestrator."""

    name: str
    enabled: bool = True
    health: str = "online"
    latency_ms: float = field(default_factory=lambda: random.uniform(15, 50))
    last_updated: float = field(default_factory=time.time)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "state": self.health,
            "enabled": self.enabled,
            "latency_ms": round(self.latency_ms, 2),
            "last_updated": self.last_updated,
        }

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.health = "online" if enabled else "offline"
        self.last_updated = time.time()

    def mark_health(self, health: str) -> None:
        self.health = health
        self.last_updated = time.time()

    def update_latency(
        self, latency_ms: float, *, health: Optional[str] = None
    ) -> None:
        self.latency_ms = max(1.0, float(latency_ms))
        self.last_updated = time.time()
        if health is not None:
            self.health = health

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


class OrchestratorState:
    """Holds runtime state for the orchestrator and synthesises status payloads."""

    def __init__(
        self,
        broker: EventBroker,
        memory: MemoryController,
        persona_presets: Dict[str, PersonaPreset],
        default_preset: str,
        policy_invoker: PolicyInvoker,
        tts_invoker: TTSInvoker,
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
        self._policy_invoker = policy_invoker
        self._tts_invoker = tts_invoker

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
            module_state = self.modules[module]
            module_state.set_enabled(enabled)
            if module == "tts_worker":
                self.tts_muted = not enabled
            payload = {
                "type": "module.toggle",
                "module": module,
                "enabled": enabled,
                "state": module_state.health,
            }
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
            self.persona.last_updated = time.time()
            body = {
                "type": "persona_update",
                "ts": self.persona.last_updated,
                "persona": self.persona.snapshot(),
                "preset": self.active_preset,
                "active_preset": self.active_preset,
            }
        await self._broker.publish(body)
        if announce:
            await self.record_turn(
                "system",
                f"Persona updated to {self.active_preset} preset.",
            )
        if log_turn and payload.system_message:
            await self.record_turn("system", payload.system_message)
        return body

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

    def _mark_module_latency(
        self, module: str, latency_ms: float, *, health: Optional[str] = None
    ) -> None:
        state = self.modules.get(module)
        if state is None:
            return
        state.update_latency(latency_ms, health=health)

    def _set_module_health(self, module: str, health: str) -> None:
        state = self.modules.get(module)
        if state is None:
            return
        state.mark_health(health)

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
            logger.exception("Failed to process ASR final event")

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
        final_payload = await self._policy_invoker(request_body, self._broker)
        latency_ms = (time.perf_counter() - start) * 1000
        if final_payload is None:
            self._mark_module_latency("policy_worker", latency_ms, health="offline")
            logger.warning("Policy worker returned no final payload for request")
            return None
        status_meta = None
        if isinstance(final_payload, dict):
            meta = final_payload.get("meta")
            if isinstance(meta, dict):
                status_meta = meta.get("status")
        if isinstance(status_meta, str) and status_meta.lower() == "error":
            self._mark_module_latency("policy_worker", latency_ms, health="offline")
        else:
            self._mark_module_latency("policy_worker", latency_ms, health="online")

        await self._broker.publish({"type": "policy_final", "payload": final_payload})

        speech_content = _extract_speech(final_payload.get("content", ""))
        if not speech_content:
            speech_content = (final_payload.get("content") or "").strip()
        if not speech_content:
            return final_payload

        if not synthesize or self.tts_muted:
            await self.record_turn("assistant", speech_content)
            return final_payload

        tts_start = time.perf_counter()
        tts_result = await self._tts_invoker(
            speech_content,
            final_payload.get("meta", {}).get("voice"),
            final_payload.get("request_id"),
        )
        tts_latency_ms = (time.perf_counter() - tts_start) * 1000
        if tts_result is not None:
            self._mark_module_latency("tts_worker", tts_latency_ms, health="online")
            await self._broker.publish({"type": "tts_generated", "payload": tts_result})
        else:
            self._mark_module_latency("tts_worker", tts_latency_ms, health="offline")
        voice_hint = None
        if isinstance(tts_result, dict):
            voice_hint = tts_result.get("voice")
        await self.record_tts(
            TTSRequestPayload(
                text=speech_content,
                voice=voice_hint,
                request_id=final_payload.get("request_id"),
            )
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
            "type": "control_preset",
            "preset": preset,
            "active_preset": preset,
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


def _extract_speech(content: Optional[str]) -> str:
    if not content:
        return ""
    match = _SPEECH_PATTERN.search(content)
    if not match:
        return ""
    value = html.unescape(match.group(1))
    return value.strip()


__all__ = [
    "ModuleState",
    "OrchestratorState",
    "PersonaState",
    "PolicyInvoker",
    "TTSInvoker",
]
