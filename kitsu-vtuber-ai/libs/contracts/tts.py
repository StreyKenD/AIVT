from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class TTSRequestPayload(BaseModel):
    """Payload posted to the TTS worker."""

    text: str = Field(..., min_length=1, description="Raw text to synthesise.")
    voice: Optional[str] = Field(
        None, description="Preferred voice identifier understood by the worker."
    )
    request_id: Optional[str] = Field(
        None,
        description="Optional correlation identifier forwarded to telemetry.",
        max_length=120,
    )


class TTSResponsePayload(BaseModel):
    """Response returned by the TTS worker."""

    audio_path: str = Field(..., description="Filesystem path to the generated audio.")
    voice: str = Field(..., description="Voice used by the synthesiser.")
    latency_ms: float = Field(
        ..., ge=0.0, description="Observed latency in milliseconds."
    )
    visemes: List[Dict[str, float]] = Field(
        default_factory=list, description="Viseme timings accompanying the audio."
    )
    cached: bool = Field(
        ..., description="Indicates whether the response came from cache."
    )


__all__ = ["TTSRequestPayload", "TTSResponsePayload"]
