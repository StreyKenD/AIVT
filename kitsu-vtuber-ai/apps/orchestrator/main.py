from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
import yaml
from fastapi import FastAPI

from libs.common import configure_json_logging
from libs.config import PersonaPreset, PersonaSettings, get_app_config
from libs.memory import MemoryController
from libs.telemetry import TelemetryClient
from libs.telemetry.gpu import GPUMonitor

from .broker import EventBroker
from .deps import set_broker, set_state
from .routes import ALL_ROUTERS
from .state import OrchestratorState


configure_json_logging("orchestrator")
logger = logging.getLogger(__name__)

settings = get_app_config()
orchestrator_cfg = settings.orchestrator
policy_cfg = settings.policy
tts_cfg = settings.tts
memory_cfg = settings.memory
persona_cfg = settings.persona

POLICY_URL = policy_cfg.url
POLICY_TIMEOUT_SECONDS = orchestrator_cfg.policy_timeout_seconds
TTS_API_URL = tts_cfg.url
TTS_TIMEOUT_SECONDS = orchestrator_cfg.tts_timeout_seconds

_policy_client: Optional[httpx.AsyncClient] = None
_tts_client: Optional[httpx.AsyncClient] = None


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
        except OSError as exc:  # pragma: no cover - defensive guard
            logger.warning("Failed to read persona presets file %s: %s", preset_path, exc)
        else:
            loaded = yaml.safe_load(raw) or {}
            if isinstance(loaded, dict):
                for name, value in loaded.items():
                    try:
                        presets[name] = PersonaPreset.model_validate(value)
                    except Exception as exc:  # pragma: no cover - malformed preset
                        logger.debug("Invalid preset %s in %s: %s", name, preset_path, exc)
    return presets


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


app = FastAPI(title="Kitsu Orchestrator", version="0.2.0")

_events_telemetry = (
    TelemetryClient(
        orchestrator_cfg.telemetry_url,
        api_key=orchestrator_cfg.telemetry_api_key,
        source="orchestrator",
    )
    if orchestrator_cfg.telemetry_url
    else None
)

broker = EventBroker(_events_telemetry)

memory_controller = MemoryController(
    buffer_size=memory_cfg.buffer_size,
    summary_interval=memory_cfg.summary_interval,
    history_path=Path(memory_cfg.history_path).expanduser(),
)

persona_presets = _load_persona_presets(persona_cfg)

state = OrchestratorState(
    broker,
    memory_controller,
    persona_presets=persona_presets,
    default_preset=persona_cfg.default,
    policy_invoker=_invoke_policy,
    tts_invoker=_invoke_tts,
)

set_broker(broker)
set_state(state)

gpu_telemetry = (
    TelemetryClient(
        orchestrator_cfg.telemetry_url,
        api_key=orchestrator_cfg.telemetry_api_key,
        source="orchestrator.gpu",
    )
    if orchestrator_cfg.telemetry_url
    else None
)

gpu_monitor = GPUMonitor(
    gpu_telemetry,
    interval_seconds=orchestrator_cfg.gpu_metrics_interval_seconds,
)

for router in ALL_ROUTERS:
    app.include_router(router)


@app.on_event("startup")
async def on_startup() -> None:
    global _policy_client, _tts_client
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
    await state.startup(memory_cfg.restore_context, memory_cfg.restore_window_seconds)
    state.start_background_tasks()
    await gpu_monitor.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _policy_client, _tts_client
    await state.shutdown()
    await gpu_monitor.stop()
    if _events_telemetry is not None:
        await _events_telemetry.aclose()
    if _policy_client is not None:
        await _policy_client.aclose()
        _policy_client = None
    if _tts_client is not None:
        await _tts_client.aclose()
        _tts_client = None
