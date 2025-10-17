from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Optional

from .logger import logger


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
    input_device: Optional[str]
    fake_audio: bool
    device_preference: str
    compute_type: Optional[str]

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
    orchestrator_url = os.getenv("ORCHESTRATOR_URL")
    if not orchestrator_url:
        host = os.getenv("ORCH_HOST", "127.0.0.1")
        port = int(os.getenv("ORCH_PORT", "8000"))
        orchestrator_url = f"http://{host}:{port}"

    model_name = os.getenv("ASR_MODEL", "small.en")
    sample_rate = int(os.getenv("ASR_SAMPLE_RATE", "16000"))
    frame_duration_ms = int(os.getenv("ASR_FRAME_MS", "20"))
    partial_interval_ms = int(os.getenv("ASR_PARTIAL_INTERVAL_MS", "200"))
    silence_duration_ms = int(os.getenv("ASR_SILENCE_MS", "500"))
    vad_mode = os.getenv("ASR_VAD", "webrtc")
    vad_aggressiveness = int(os.getenv("ASR_VAD_AGGRESSIVENESS", "2"))
    input_device = os.getenv("ASR_INPUT_DEVICE")
    fake_audio = os.getenv("ASR_FAKE_AUDIO", "0").lower() in {"1", "true", "yes"}
    device_preference = os.getenv("ASR_DEVICE", "cuda")
    compute_type = os.getenv("ASR_COMPUTE_TYPE")

    if vad_mode.lower() == "webrtc":
        allowed_frames = {10, 20, 30}
        if frame_duration_ms not in allowed_frames:
            closest = min(allowed_frames, key=lambda opt: abs(opt - frame_duration_ms))
            logger.warning(
                "ASR_FRAME_MS=%s is not supported by WebRTC VAD (use 10, 20, or 30). "
                "Adjusting to %s ms.",
                frame_duration_ms,
                closest,
            )
            frame_duration_ms = closest

    return ASRConfig(
        model_name=model_name,
        orchestrator_url=orchestrator_url,
        sample_rate=sample_rate,
        frame_duration_ms=frame_duration_ms,
        partial_interval_ms=partial_interval_ms,
        silence_duration_ms=silence_duration_ms,
        vad_mode=vad_mode,
        vad_aggressiveness=vad_aggressiveness,
        input_device=input_device,
        fake_audio=fake_audio,
        device_preference=device_preference,
        compute_type=compute_type,
    )


__all__ = ["ASRConfig", "load_config"]
