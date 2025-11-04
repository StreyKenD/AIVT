from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Tuple

import yaml

from .models import AppSettings


logger = logging.getLogger(__name__)
_CONFIG_CACHE: AppSettings | None = None


def get_app_config() -> AppSettings:
    """Return the cached application settings, loading them if necessary."""

    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = _load_settings()
    return _CONFIG_CACHE


def reload_app_config() -> AppSettings:
    """Reload the configuration from disk, bypassing the cache."""

    global _CONFIG_CACHE
    _CONFIG_CACHE = _load_settings()
    return _CONFIG_CACHE


def _load_settings() -> AppSettings:
    raw = _load_raw_config()
    merged = _apply_env_overrides(raw)
    settings = AppSettings.model_validate(merged)
    return settings.resolved()


def _load_raw_config() -> Dict[str, Any]:
    path = Path(os.getenv("KITSU_CONFIG_FILE", "config/kitsu.yaml"))
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Unable to read config file at {path}: {exc}") from exc
    if not text.strip():
        return {}
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise RuntimeError(f"Invalid YAML in config file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Top-level structure in {path} must be a mapping.")
    return data


def _apply_env_overrides(source: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = copy.deepcopy(source)
    for env_name, overrides in _ENV_MAPPING.items():
        raw_value = os.getenv(env_name)
        if raw_value is None or raw_value == "":
            continue
        for path, transformer in overrides:
            try:
                value = transformer(raw_value) if transformer else raw_value
            except Exception as exc:
                logger.warning("Ignoring invalid value for %s: %s", env_name, exc)
                continue
            _assign_path(result, path, value)
    return result


def _assign_path(target: Dict[str, Any], path: Tuple[str, ...], value: Any) -> None:
    current: Dict[str, Any] = target
    for key in path[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[path[-1]] = value


def _to_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _split_csv(value: str) -> Iterable[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _to_int(value: str) -> int:
    return int(value.strip())


def _to_float(value: str) -> float:
    return float(value.strip())


def _to_mapping(value: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for item in _split_csv(value):
        if not item or ":" not in item:
            continue
        key, raw_val = item.split(":", 1)
        key = key.strip()
        val = raw_val.strip()
        if key:
            mapping[key] = val
    return mapping


def _to_int_clamped(min_value: int, max_value: int) -> Callable[[str], int]:
    def transformer(value: str) -> int:
        candidate = int(value.strip())
        if candidate < min_value:
            return min_value
        if candidate > max_value:
            return max_value
        return candidate

    return transformer


def _strip_or_none(value: str) -> str | None:
    stripped = value.strip()
    return stripped or None


def _map(
    path: Tuple[str, ...], transformer: Callable[[str], Any] | None = None
) -> Tuple[Tuple[str, ...], Callable[[str], Any] | None]:
    return path, transformer


_ENV_MAPPING: Dict[str, list[Tuple[Tuple[str, ...], Callable[[str], Any] | None]]] = {}


def _register(
    env: str, *paths: Tuple[Tuple[str, ...], Callable[[str], Any] | None]
) -> None:
    bucket = _ENV_MAPPING.setdefault(env, [])
    bucket.extend(paths)


# Populate environment mapping.
_register("KITSU_CONFIG_VERSION", _map(("version",)))

_register(
    "ORCH_HOST",
    _map(("orchestrator", "bind_host")),
)
_register(
    "ORCH_PORT",
    _map(("orchestrator", "bind_port")),
)
_register(
    "ORCH_CORS_ALLOW_ALL",
    _map(("orchestrator", "cors_allow_all"), _to_bool),
)
_register(
    "ORCH_CORS_ALLOW_ORIGINS",
    _map(("orchestrator", "cors_allow_origins"), lambda value: list(_split_csv(value))),
)
_register(
    "ORCHESTRATOR_URL",
    _map(("orchestrator", "public_url")),
    _map(("asr", "orchestrator_url")),
)
_register(
    "POLICY_TIMEOUT_SECONDS",
    _map(("orchestrator", "policy_timeout_seconds")),
)
_register(
    "TTS_TIMEOUT_SECONDS",
    _map(("orchestrator", "tts_timeout_seconds")),
    _map(("tts", "timeout_seconds")),
)
_register(
    "TELEMETRY_API_URL",
    _map(("orchestrator", "telemetry_url")),
)
_register(
    "TELEMETRY_BASE_URL",
    _map(("orchestrator", "telemetry_url")),
)
_register(
    "TELEMETRY_API_KEY",
    _map(("orchestrator", "telemetry_api_key")),
)
_register(
    "GPU_METRICS_INTERVAL_SECONDS",
    _map(("orchestrator", "gpu_metrics_interval_seconds")),
)

_register(
    "POLICY_URL",
    _map(("policy", "endpoint_url")),
)
_register(
    "POLICY_HOST",
    _map(("policy", "bind_host")),
)
_register(
    "POLICY_PORT",
    _map(("policy", "bind_port")),
)
_register(
    "POLICY_STREAM_TIMEOUT",
    _map(("policy", "stream_timeout")),
)
_register(
    "POLICY_RETRY_ATTEMPTS",
    _map(("policy", "retry_attempts")),
)
_register(
    "POLICY_RETRY_BACKOFF",
    _map(("policy", "retry_backoff")),
)
_register(
    "POLICY_TEMPERATURE",
    _map(("policy", "temperature")),
)
_register(
    "POLICY_FAMILY_FRIENDLY",
    _map(("policy", "family_friendly"), _to_bool),
)
_register(
    "POLICY_BACKEND",
    _map(("policy", "backend"), lambda value: value.strip().lower()),
)
_register(
    "LLM_MODEL_NAME",
    _map(("policy", "model_name")),
)
_register(
    "OLLAMA_URL",
    _map(("policy", "ollama_url")),
)
_register(
    "OPENAI_API_KEY_ENV",
    _map(("policy", "openai", "api_key_env")),
)
_register(
    "OPENAI_MODEL",
    _map(("policy", "openai", "model")),
)
_register(
    "OPENAI_BASE_URL",
    _map(("policy", "openai", "base_url")),
)
_register(
    "OPENAI_ORGANIZATION",
    _map(("policy", "openai", "organization")),
)
_register(
    "OPENAI_TIMEOUT_SECONDS",
    _map(("policy", "openai", "timeout_seconds"), _to_float),
)
_register(
    "LOCAL_LLM_ENGINE",
    _map(("policy", "local", "engine"), lambda value: value.strip().lower()),
)
_register(
    "LOCAL_LLM_MODEL_PATH",
    _map(("policy", "local", "model_path")),
)
_register(
    "LOCAL_LLM_TOKENIZER_PATH",
    _map(("policy", "local", "tokenizer_path")),
)
_register(
    "LOCAL_LLM_DEVICE",
    _map(("policy", "local", "device")),
)
_register(
    "LOCAL_LLM_MAX_NEW_TOKENS",
    _map(("policy", "local", "max_new_tokens"), _to_int),
)
_register(
    "LOCAL_LLM_TEMPERATURE",
    _map(("policy", "local", "temperature"), _to_float),
)

_register(
    "TTS_HOST",
    _map(("tts", "bind_host")),
)
_register(
    "TTS_PORT",
    _map(("tts", "bind_port")),
)
_register(
    "TTS_API_URL",
    _map(("tts", "endpoint_url")),
)
_register(
    "TTS_CACHE_DIR",
    _map(("tts", "cache_dir")),
)

_register(
    "TTS_BACKEND",
    _map(("tts", "backend"), lambda value: value.strip().lower()),
)
_register(
    "TTS_FALLBACKS",
    _map(
        ("tts", "fallback_backends"),
        lambda value: [item.strip().lower() for item in _split_csv(value)],
    ),
)
_register(
    "TTS_MODEL_NAME",
    _map(("tts", "coqui", "model_name")),
)
_register(
    "TTS_DEFAULT_SPEAKER",
    _map(("tts", "coqui", "default_speaker")),
)
_register(
    "TTS_SPEAKER_MAP",
    _map(("tts", "coqui", "speaker_map"), _to_mapping),
)
_register(
    "PIPER_PATH",
    _map(("tts", "piper", "binary")),
)
_register(
    "PIPER_MODEL",
    _map(("tts", "piper", "model")),
)
_register(
    "PIPER_CONFIG",
    _map(("tts", "piper", "config")),
)
_register(
    "PIPER_DEFAULT_SPEAKER",
    _map(("tts", "piper", "default_speaker")),
)
_register(
    "PIPER_SPEAKER_MAP",
    _map(("tts", "piper", "speaker_map"), _to_mapping),
)
_register(
    "BARK_VOICE_PRESET",
    _map(("tts", "bark", "voice_preset")),
)
_register(
    "BARK_HISTORY_PROMPT",
    _map(("tts", "bark", "history_prompt")),
)
_register(
    "BARK_TEXT_TEMPERATURE",
    _map(("tts", "bark", "text_temperature"), _to_float),
)
_register(
    "BARK_WAVEFORM_TEMPERATURE",
    _map(("tts", "bark", "waveform_temperature"), _to_float),
)
_register(
    "BARK_SPEAKER_PROMPTS",
    _map(("tts", "bark", "speaker_prompts"), _to_mapping),
)
_register(
    "XTTS_MODEL_NAME",
    _map(("tts", "xtts", "model_name")),
)
_register(
    "XTTS_SPEAKER_WAV",
    _map(("tts", "xtts", "default_speaker_wav")),
)
_register(
    "XTTS_SPEAKER_NAME",
    _map(("tts", "xtts", "default_speaker_name")),
)
_register(
    "XTTS_LANGUAGE",
    _map(("tts", "xtts", "default_language")),
)
_register(
    "XTTS_SPEAKERS",
    _map(("tts", "xtts", "speaker_wavs"), _to_mapping),
)
_register(
    "XTTS_LANGUAGE_OVERRIDES",
    _map(("tts", "xtts", "language_overrides"), _to_mapping),
)

_register(
    "ASR_MODEL",
    _map(("asr", "model_name")),
)
_register(
    "ASR_BACKEND",
    _map(("asr", "backend"), lambda value: value.strip().lower()),
)
_register(
    "ASR_SAMPLE_RATE",
    _map(("asr", "sample_rate"), _to_int),
)
_register(
    "ASR_FRAME_MS",
    _map(("asr", "frame_duration_ms"), _to_int),
)
_register(
    "ASR_PARTIAL_INTERVAL_MS",
    _map(("asr", "partial_interval_ms"), _to_int),
)
_register(
    "ASR_SILENCE_MS",
    _map(("asr", "silence_duration_ms"), _to_int),
)
_register(
    "ASR_VAD",
    _map(("asr", "vad_mode")),
)
_register(
    "ASR_VAD_AGGRESSIVENESS",
    _map(("asr", "vad_aggressiveness"), _to_int_clamped(0, 3)),
)
_register(
    "ASR_INPUT_DEVICE",
    _map(("asr", "input_device")),
)
_register(
    "ASR_FAKE_AUDIO",
    _map(("asr", "fake_audio"), _to_bool),
)
_register(
    "ASR_DEVICE",
    _map(("asr", "device_preference")),
)
_register(
    "ASR_COMPUTE_TYPE",
    _map(("asr", "compute_type"), _strip_or_none),
)
_register(
    "ASR_ALLOW_NON_ENGLISH",
    _map(("asr", "allow_non_english"), _to_bool),
)
_register(
    "ASR_SHERPA_CONFIG",
    _map(("asr", "sherpa", "config_file")),
)
_register(
    "ASR_SHERPA_TOKENS",
    _map(("asr", "sherpa", "tokens")),
)
_register(
    "ASR_SHERPA_ENCODER",
    _map(("asr", "sherpa", "encoder")),
)
_register(
    "ASR_SHERPA_DECODER",
    _map(("asr", "sherpa", "decoder")),
)
_register(
    "ASR_SHERPA_JOINER",
    _map(("asr", "sherpa", "joiner")),
)
_register(
    "ASR_SHERPA_MODEL_TYPE",
    _map(("asr", "sherpa", "model_type")),
)
_register(
    "ASR_SHERPA_NUM_THREADS",
    _map(("asr", "sherpa", "num_threads"), _to_int),
)
_register(
    "ASR_SHERPA_PROVIDER",
    _map(("asr", "sherpa", "provider")),
)
_register(
    "ASR_SHERPA_DECODING_METHOD",
    _map(("asr", "sherpa", "decoding_method")),
)
_register(
    "RESTORE_CONTEXT",
    _map(("memory", "restore_context"), _to_bool),
)
_register(
    "MEMORY_RESTORE_WINDOW_SECONDS",
    _map(("memory", "restore_window_seconds")),
)
_register(
    "MEMORY_BUFFER_SIZE",
    _map(("memory", "buffer_size"), _to_int),
)
_register(
    "MEMORY_SUMMARY_INTERVAL",
    _map(("memory", "summary_interval"), _to_int),
)
_register(
    "MEMORY_HISTORY_PATH",
    _map(("memory", "history_path")),
)
_register(
    "PERSONA_DEFAULT",
    _map(("persona", "default")),
)
_register(
    "PERSONA_PRESETS_FILE",
    _map(("persona", "presets_file")),
)
