from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from libs.config import reload_app_config


@dataclass
class SherpaConfig:
    config_file: Optional[str] = None
    tokens: Optional[str] = None
    encoder: Optional[str] = None
    decoder: Optional[str] = None
    joiner: Optional[str] = None
    model_type: str = "transducer"
    num_threads: int = 2
    provider: str = "cpu"
    decoding_method: str = "greedy_search"


@dataclass
class ASRConfig:
    model_name: str
    orchestrator_url: str
    sample_rate: int
    frame_duration_ms: int
    partial_interval_ms: int
    silence_duration_ms: int
    vad_mode: str
    vad_aggressiveness: int
    input_device: str | int | None
    fake_audio: bool
    device_preference: str
    compute_type: Optional[str]
    allow_non_english: bool = False
    backend: str = "whisper"
    sherpa: SherpaConfig = field(default_factory=SherpaConfig)

    @property
    def frame_samples(self) -> int:
        return int(self.sample_rate * self.frame_duration_ms / 1000)

    @property
    def frame_bytes(self) -> int:
        return self.frame_samples * 2

    @property
    def partial_interval(self) -> float:
        return max(0.05, self.partial_interval_ms / 1000)

    @property
    def silence_threshold_frames(self) -> int:
        minimum_ms = max(self.silence_duration_ms, self.frame_duration_ms)
        return max(1, int(math.ceil(minimum_ms / self.frame_duration_ms)))


def load_config() -> ASRConfig:
    settings = reload_app_config().asr

    return ASRConfig(
        model_name=settings.model_name,
        orchestrator_url=settings.orchestrator_url,
        sample_rate=settings.sample_rate,
        frame_duration_ms=settings.frame_duration_ms,
        partial_interval_ms=settings.partial_interval_ms,
        silence_duration_ms=settings.silence_duration_ms,
        vad_mode=settings.vad_mode,
        vad_aggressiveness=settings.vad_aggressiveness,
        input_device=settings.input_device,
        fake_audio=settings.fake_audio,
        device_preference=settings.device_preference,
        compute_type=settings.compute_type,
        allow_non_english=settings.allow_non_english,
        backend=settings.backend,
        sherpa=SherpaConfig(
            config_file=settings.sherpa.config_file,
            tokens=settings.sherpa.tokens,
            encoder=settings.sherpa.encoder,
            decoder=settings.sherpa.decoder,
            joiner=settings.sherpa.joiner,
            model_type=settings.sherpa.model_type,
            num_threads=settings.sherpa.num_threads,
            provider=settings.sherpa.provider,
            decoding_method=settings.sherpa.decoding_method,
        ),
    )


__all__ = ["ASRConfig", "SherpaConfig", "load_config"]
