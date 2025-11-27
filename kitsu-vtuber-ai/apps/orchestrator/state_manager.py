"""High-level state manager for the orchestrator service.

This module tracks persona/module state, coordinates background tasks, and
delegates decision making to :mod:`apps.orchestrator.decision_engine` while
using :mod:`apps.orchestrator.event_dispatcher` to broadcast events.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from libs.config import PersonaPreset
from libs.contracts import (
    ASREventPayload,
    PersonaUpdateCommand,
    TTSRequestPayload,
    VTSExpressionCommand,
)
from libs.memory import MemoryController, MemorySummary

from .broker import EventBroker
from .decision_engine import DecisionEngine
from .event_dispatcher import EventDispatcher

logger = logging.getLogger(__name__)

PolicyStreamHandler = Callable[[str, Dict[str, Any]], Awaitable[None]]
PolicyInvoker = Callable[
    [Dict[str, Any], EventBroker, Optional[PolicyStreamHandler]],
    Awaitable[Optional[Dict[str, Any]]],
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
        self._dispatcher = EventDispatcher(broker)
        self.memory = memory
        self._tasks: List[asyncio.Task[Any]] = []
        self._lock = asyncio.Lock()
        self.restore_context = False
        self._started_at = time.time()
        self.last_summary: Optional[MemorySummary] = None
        self.tts_muted = False
        self.panic_triggered_at: Optional[float] = None
        self.panic_reason: Optional[str] = None
        self.active_preset = default_preset
        self._decision_engine = DecisionEngine(
            self,
            self._dispatcher,
            policy_invoker,
            tts_invoker,
        )

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
            await self._dispatcher.publish(
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
        await self._dispatcher.publish(payload)
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
        preset_name: Optional[str] = None,
        announce: bool = False,
    ) -> Dict[str, Any]:
        async with self._lock:
            self.persona.update(
                style=payload.style,
                chaos_level=payload.chaos_level,
                energy=payload.energy,
                family_mode=payload.family_mode,
            )
            if preset_name:
                self.active_preset = preset_name
            elif payload.style or payload.chaos_level or payload.energy:
                self.active_preset = "custom"
            snapshot = {
                "active_preset": self.active_preset,
                "persona": self.persona.snapshot(),
            }
            if announce:
                event = {
                    "type": "persona_update",
                    "persona": self.persona.snapshot(),
                }
            else:
                event = None
        if event:
            await self._dispatcher.publish(event)
        return snapshot

    async def update_persona(self, payload: PersonaUpdateCommand) -> Dict[str, Any]:
        return await self._apply_persona_update(payload, announce=True)

    async def handle_asr_partial(self, event: ASREventPayload) -> None:
        """Handle `asr_partial` events forwarded by the orchestrator route."""
        await self._decision_engine.handle_asr_partial(event)

    async def handle_asr_final(self, event: ASREventPayload) -> None:
        """Handle final ASR segments and trigger the policy pipeline."""
        await self._decision_engine.handle_asr_final(event)

    async def process_manual_prompt(
        self, text: str, *, synthesize: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Inject a manual chat turn (used by /chat/respond)."""
        return await self._decision_engine.process_manual_prompt(
            text, synthesize=synthesize
        )

    async def update_scene(self, scene: str) -> Dict[str, Any]:
        async with self._lock:
            self.current_scene = scene
            payload = {"type": "obs_scene", "scene": scene, "ts": time.time()}
        await self._dispatcher.publish(payload)
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
        await self._dispatcher.publish(payload)
        return payload

    async def record_turn(self, role: str, text: str) -> Optional[Dict[str, Any]]:
        summary = await self.memory.add_turn(role, text)
        if summary is None:
            return None
        self.last_summary = summary
        payload = {"type": "memory_summary", "summary": summary.to_dict()}
        await self._dispatcher.publish(payload)
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
        await self._dispatcher.publish(payload)
        return payload

    async def set_mute(self, muted: bool) -> Dict[str, Any]:
        async with self._lock:
            self.tts_muted = muted
            payload = {
                "type": "control.mute",
                "muted": muted,
                "ts": time.time(),
            }
        await self._dispatcher.publish(payload)
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
        await self._dispatcher.publish(payload)
        return payload

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
        await self._dispatcher.publish(payload)
        summary_payload = await self.record_turn("assistant", request.text)
        payload["summary_generated"] = summary_payload is not None
        return payload

    def uptime_seconds(self) -> float:
        return max(0.0, time.time() - self._started_at)

    def health_snapshot(self) -> Dict[str, Any]:
        """Return a lightweight view of module health for /health."""
        modules = {name: module.health for name, module in self.modules.items()}
        status = "online"
        if any(state == "offline" for state in modules.values()):
            status = "offline"
        elif any(state == "degraded" for state in modules.values()):
            status = "degraded"
        snapshot = {
            "status": status,
            "uptime_seconds": round(self.uptime_seconds(), 2),
            "modules": modules,
            "tts_muted": self.tts_muted,
            "panic_reason": self.panic_reason,
            "panic_active": self.panic_reason is not None,
        }
        return snapshot

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

    @property
    def _policy_invoker(self) -> PolicyInvoker:
        return self._decision_engine.policy_invoker

    @_policy_invoker.setter
    def _policy_invoker(self, invoker: PolicyInvoker) -> None:
        self._decision_engine.update_policy_invoker(invoker)

    @property
    def _tts_invoker(self) -> TTSInvoker:
        return self._decision_engine.tts_invoker

    @_tts_invoker.setter
    def _tts_invoker(self, invoker: TTSInvoker) -> None:
        self._decision_engine.update_tts_invoker(invoker)

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
                snapshot = self.snapshot()
            await self._dispatcher.publish_status(snapshot)


__all__ = [
    "ModuleState",
    "OrchestratorState",
    "PersonaState",
    "PolicyStreamHandler",
    "PolicyInvoker",
    "TTSInvoker",
]
