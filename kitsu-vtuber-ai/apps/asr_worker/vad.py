from __future__ import annotations

from typing import Protocol, cast

from .config import ASRConfig
from .utils import load_module_if_available


class VoiceActivityDetector(Protocol):
    def is_speech(self, frame: bytes) -> bool:
        """Return True if the frame contains speech."""


class WebRtcVadLike(Protocol):
    def is_speech(self, frame: bytes, sample_rate: int) -> bool: ...


class WebRtcVadModule(Protocol):
    def Vad(self, aggressiveness: int) -> WebRtcVadLike: ...


class PassthroughVAD:
    supports_silence_detection = False

    def __init__(self, frame_bytes: int) -> None:
        self._frame_bytes = frame_bytes

    def is_speech(self, frame: bytes) -> bool:
        if len(frame) != self._frame_bytes:
            raise ValueError("Unexpected frame size for VAD passthrough")
        return True


class WebRtcVAD:
    def __init__(self, vad: WebRtcVadLike, frame_bytes: int, sample_rate: int) -> None:
        self._vad = vad
        self._frame_bytes = frame_bytes
        self._sample_rate = sample_rate

    def is_speech(self, frame: bytes) -> bool:
        if len(frame) != self._frame_bytes:
            raise ValueError("Frame size mismatch for WebRTC VAD")
        return bool(self._vad.is_speech(frame, self._sample_rate))


def build_vad(config: ASRConfig) -> VoiceActivityDetector:
    if config.vad_mode.lower() == "none":
        return PassthroughVAD(config.frame_bytes)
    if config.vad_mode.lower() != "webrtc":
        raise RuntimeError(f"Unsupported VAD mode: {config.vad_mode}")
    vad_module_obj = load_module_if_available("webrtcvad")
    if vad_module_obj is None:
        raise RuntimeError("webrtcvad is not installed; set ASR_VAD=none to proceed")
    vad_module = cast(WebRtcVadModule, vad_module_obj)
    vad = vad_module.Vad(config.vad_aggressiveness)
    return WebRtcVAD(vad, config.frame_bytes, config.sample_rate)


__all__ = [
    "PassthroughVAD",
    "VoiceActivityDetector",
    "WebRtcVAD",
    "build_vad",
]
