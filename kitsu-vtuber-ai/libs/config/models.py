from __future__ import annotations

import warnings
from typing import Any, Dict, List, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


def _to_bool(value: Union[str, bool]) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "on", "y"}


class OrchestratorSettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    bind_host: str = "0.0.0.0"
    bind_port: int = 8000
    public_url: Optional[str] = None
    policy_timeout_seconds: float = Field(40.0, ge=0.0)
    tts_timeout_seconds: float = Field(60.0, ge=0.0)
    telemetry_url: Optional[str] = None
    telemetry_api_key: Optional[str] = None
    api_key: Optional[str] = None
    cors_allow_all: bool = False
    cors_allow_origins: List[str] = Field(default_factory=list)
    gpu_metrics_interval_seconds: float = Field(30.0, ge=5.0)

    @computed_field(return_type=str)
    def base_url(self) -> str:
        url = self.public_url
        if url:
            return url.rstrip("/")
        return f"http://127.0.0.1:{self.bind_port}"


class OpenAISettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    api_key_env: str = "OPENAI_API_KEY"
    model: Optional[str] = None
    base_url: str = "https://api.openai.com/v1"
    organization: Optional[str] = None
    timeout_seconds: float = Field(60.0, ge=1.0)


class LocalLLMSettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    engine: str = "transformers"
    model_path: Optional[str] = None
    tokenizer_path: Optional[str] = None
    device: str = "auto"
    max_new_tokens: int = Field(512, ge=1)
    temperature: float = Field(0.7, ge=0.0, le=2.0)


class PersonaPreset(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    style: str = "kawaii"
    chaos_level: float = Field(0.2, ge=0.0, le=1.0)
    energy: float = Field(0.5, ge=0.0, le=1.0)
    family_mode: bool = True
    system_prompt: Optional[str] = None


def _default_persona_presets() -> Dict[str, "PersonaPreset"]:
    return {
        "default": PersonaPreset(
            style="kawaii",
            chaos_level=0.2,
            energy=0.5,
            family_mode=True,
            system_prompt=None,
        ),
        "cozy": PersonaPreset(
            style="calm",
            chaos_level=0.15,
            energy=0.35,
            family_mode=True,
            system_prompt=None,
        ),
        "hype": PersonaPreset(
            style="chaotic",
            chaos_level=0.75,
            energy=0.85,
            family_mode=True,
            system_prompt=None,
        ),
    }


class PersonaSettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    default: str = "default"
    presets: Dict[str, PersonaPreset] = Field(default_factory=_default_persona_presets)
    presets_file: Optional[str] = None


class PolicySettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    bind_host: str = "0.0.0.0"
    bind_port: int = 8081
    endpoint_url: Optional[str] = None
    model_name: str = "mixtral:7b-instruct-v0.1-q4_0"
    backend: str = "ollama"
    family_friendly: bool = True
    stream_timeout: float = Field(30.0, ge=1.0)
    retry_attempts: int = Field(1, ge=0)
    retry_backoff: float = Field(1.0, ge=0.0)
    temperature: float = Field(0.65, ge=0.0, le=2.0)
    ollama_url: str = "http://localhost:11434"
    openai: OpenAISettings = Field(default_factory=lambda: OpenAISettings())
    local: LocalLLMSettings = Field(default_factory=lambda: LocalLLMSettings())
    memory_cache_max_entries: int = Field(128, ge=1)
    memory_cache_ttl_seconds: float = Field(300.0, ge=1.0)
    resource_cpu_threshold_pct: float = Field(85.0, ge=0.0, le=100.0)
    resource_gpu_threshold_pct: float = Field(95.0, ge=0.0, le=100.0)
    resource_check_interval_seconds: float = Field(1.0, ge=0.1)
    resource_busy_timeout_seconds: float = Field(0.0, ge=0.0)
    resource_busy_timeout_seconds: float = Field(2.0, ge=0.0)

    @computed_field(return_type=str)
    def url(self) -> str:
        candidate = self.endpoint_url
        if candidate:
            return candidate.rstrip("/")
        return f"http://127.0.0.1:{self.bind_port}"

    @model_validator(mode="after")
    def _normalise_backend(self) -> "PolicySettings":
        normalized = (self.backend or "ollama").strip().lower()
        object.__setattr__(self, "backend", normalized)
        return self


class CoquiTTSSettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    model_name: str = "tts_models/en/vctk/vits"
    default_speaker: Optional[str] = None
    speaker_map: Dict[str, str] = Field(default_factory=dict)


class PiperTTSSettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    binary: str = "piper"
    model: str = ""
    config: Optional[str] = None
    default_speaker: Optional[str] = None
    speaker_map: Dict[str, str] = Field(default_factory=dict)


class BarkTTSSettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    voice_preset: str = "v2/en_speaker_9"
    history_prompt: Optional[str] = None
    text_temperature: float = Field(0.7, ge=0.0, le=2.0)
    waveform_temperature: float = Field(0.7, ge=0.0, le=2.0)
    speaker_prompts: Dict[str, str] = Field(default_factory=dict)


class XTTSSettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    model_name: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    default_speaker_wav: Optional[str] = None
    default_speaker_name: Optional[str] = None
    default_language: str = "en"
    speaker_wavs: Dict[str, str] = Field(default_factory=dict)
    language_overrides: Dict[str, str] = Field(default_factory=dict)

    @field_validator("default_language", mode="before")
    @classmethod
    def _normalise_language(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        return value.strip().lower() or "en"

    @field_validator("language_overrides", mode="before")
    @classmethod
    def _normalise_language_overrides(cls, value: Dict[str, str]) -> Dict[str, str]:
        if not isinstance(value, dict):
            return value
        return {
            key: (val.strip().lower() if isinstance(val, str) else val)
            for key, val in value.items()
        }


class TTSSettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    bind_host: str = "0.0.0.0"
    bind_port: int = 8070
    endpoint_url: Optional[str] = None
    timeout_seconds: float = Field(60.0, ge=0.0)
    cache_dir: str = "artifacts/tts_cache"
    backend: str = "auto"
    fallback_backends: List[str] = Field(default_factory=list)
    coqui: CoquiTTSSettings = Field(default_factory=lambda: CoquiTTSSettings())
    piper: PiperTTSSettings = Field(default_factory=lambda: PiperTTSSettings())
    bark: BarkTTSSettings = Field(default_factory=lambda: BarkTTSSettings())
    xtts: XTTSSettings = Field(default_factory=lambda: XTTSSettings())
    memory_cache_max_entries: int = Field(128, ge=1)
    memory_cache_ttl_seconds: float = Field(300.0, ge=1.0)
    resource_cpu_threshold_pct: float = Field(85.0, ge=0.0, le=100.0)
    resource_gpu_threshold_pct: float = Field(95.0, ge=0.0, le=100.0)
    resource_check_interval_seconds: float = Field(1.0, ge=0.1)
    resource_busy_timeout_seconds: float = Field(2.0, ge=0.0)

    @computed_field(return_type=str)
    def url(self) -> str:
        candidate = self.endpoint_url
        if candidate:
            return candidate.rstrip("/")
        return f"http://127.0.0.1:{self.bind_port}"

    @model_validator(mode="after")
    def _normalise_backends(self) -> "TTSSettings":
        backend = (self.backend or "auto").strip().lower()
        object.__setattr__(self, "backend", backend)
        normalised: List[str] = []
        for item in self.fallback_backends:
            if not isinstance(item, str):
                continue
            candidate = item.strip().lower()
            if candidate and candidate not in normalised and candidate != backend:
                normalised.append(candidate)
        object.__setattr__(self, "fallback_backends", normalised)
        return self


class SherpaSettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    config_file: Optional[str] = None
    tokens: Optional[str] = None
    encoder: Optional[str] = None
    decoder: Optional[str] = None
    joiner: Optional[str] = None
    model_type: str = "transducer"
    num_threads: int = Field(2, ge=1)
    provider: str = "cpu"
    decoding_method: str = "greedy_search"


class ASRSettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    model_name: str = "small.en"
    orchestrator_url: Optional[str] = None
    sample_rate: int = Field(16000, ge=1)
    frame_duration_ms: int = Field(20, ge=1)
    partial_interval_ms: int = Field(200, ge=1)
    silence_duration_ms: int = Field(500, ge=1)
    vad_mode: str = "webrtc"
    vad_aggressiveness: int = Field(2, ge=0, le=3)
    input_device: Optional[Union[int, str]] = None
    fake_audio: bool = False
    device_preference: str = "cuda"
    compute_type: Optional[str] = None
    allow_non_english: bool = False
    backend: str = "whisper"
    sherpa: SherpaSettings = Field(default_factory=lambda: SherpaSettings())
    resource_cpu_threshold_pct: float = Field(85.0, ge=0.0, le=100.0)
    resource_gpu_threshold_pct: float = Field(95.0, ge=0.0, le=100.0)
    resource_check_interval_seconds: float = Field(1.0, ge=0.1)

    @field_validator("vad_mode", mode="before")
    @classmethod
    def _normalise_vad_mode(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        return value.strip().lower() or "webrtc"

    @field_validator("device_preference", mode="before")
    @classmethod
    def _normalise_device(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        return value.strip().lower() or "cuda"

    @field_validator("fake_audio", mode="before")
    @classmethod
    def _parse_bool(cls, value: Union[str, bool]) -> bool:
        if isinstance(value, bool):
            return value
        return _to_bool(value)

    @field_validator("allow_non_english", mode="before")
    @classmethod
    def _parse_allow_non_english(cls, value: Union[str, bool]) -> bool:
        if isinstance(value, bool):
            return value
        return _to_bool(value)

    @field_validator("input_device", mode="before")
    @classmethod
    def _parse_input_device(
        cls, value: Union[str, int, None]
    ) -> Optional[Union[int, str]]:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        candidate = value.strip()
        if not candidate:
            return None
        if candidate.isdigit():
            try:
                return int(candidate)
            except ValueError:
                return candidate
        return candidate

    @model_validator(mode="after")
    def _adjust_intervals(self) -> "ASRSettings":
        frame_ms = self.frame_duration_ms
        if self.partial_interval_ms < frame_ms:
            self.partial_interval_ms = frame_ms
        if self.silence_duration_ms < frame_ms:
            self.silence_duration_ms = frame_ms
        if self.vad_mode.lower() == "webrtc":
            allowed = (10, 20, 30)
            if frame_ms not in allowed:
                closest = min(allowed, key=lambda option: abs(option - frame_ms))
                self.frame_duration_ms = closest
        return self

    @model_validator(mode="after")
    def _normalize_backend(self) -> "ASRSettings":
        normalized = (self.backend or "whisper").strip().lower()
        object.__setattr__(self, "backend", normalized)
        return self


class MemorySettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    restore_context: bool = False
    restore_window_seconds: float = Field(7200.0, ge=0.0)
    buffer_size: int = Field(40, ge=4)
    summary_interval: int = Field(6, ge=1)
    history_path: str = "data/memory_history.json"

    @field_validator("restore_context", mode="before")
    @classmethod
    def _parse_restore_flag(cls, value: Union[str, bool]) -> bool:
        if isinstance(value, bool):
            return value
        return _to_bool(value)


class AppSettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    version: int = 1
    orchestrator: OrchestratorSettings = Field(
        default_factory=lambda: OrchestratorSettings()
    )
    policy: PolicySettings = Field(default_factory=lambda: PolicySettings())
    tts: TTSSettings = Field(default_factory=lambda: TTSSettings())
    asr: ASRSettings = Field(default_factory=lambda: ASRSettings())
    memory: MemorySettings = Field(default_factory=lambda: MemorySettings())
    persona: PersonaSettings = Field(default_factory=lambda: PersonaSettings())

    @model_validator(mode="before")
    @classmethod
    def _migrate_orchestrator_urls(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        orchestrator = data.get("orchestrator")
        if not isinstance(orchestrator, dict):
            return data

        policy_url = orchestrator.pop("policy_url", None)
        if isinstance(policy_url, str) and policy_url.strip():
            policy = data.get("policy")
            if policy is None:
                policy = {}
                data["policy"] = policy
            if isinstance(policy, dict) and "endpoint_url" not in policy:
                policy["endpoint_url"] = policy_url
            warnings.warn(
                "orchestrator.policy_url is deprecated; use policy.endpoint_url instead",
                DeprecationWarning,
                stacklevel=2,
            )

        tts_url = orchestrator.pop("tts_url", None)
        if isinstance(tts_url, str) and tts_url.strip():
            tts = data.get("tts")
            if tts is None:
                tts = {}
                data["tts"] = tts
            if isinstance(tts, dict) and "endpoint_url" not in tts:
                tts["endpoint_url"] = tts_url
            warnings.warn(
                "orchestrator.tts_url is deprecated; use tts.endpoint_url instead",
                DeprecationWarning,
                stacklevel=2,
            )

        return data

    def resolved(self) -> "AppSettings":
        orchestrator = self.orchestrator
        asr = self.asr
        persona = self.persona

        if orchestrator.public_url is None:
            orchestrator = orchestrator.model_copy(
                update={"public_url": f"http://127.0.0.1:{orchestrator.bind_port}"}
            )
        if asr.orchestrator_url is None:
            asr = asr.model_copy(update={"orchestrator_url": orchestrator.base_url})

        if (
            persona.default not in persona.presets
            and not persona.presets_file
            and persona.presets
        ):
            fallback = next(iter(persona.presets.keys()))
            persona = persona.model_copy(update={"default": fallback})

        return self.model_copy(
            update={"orchestrator": orchestrator, "asr": asr, "persona": persona}
        )
