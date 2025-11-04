from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _ASREventBase(BaseModel):
    """Common fields emitted by the ASR worker regardless of event type."""

    model_config = ConfigDict(frozen=True)

    segment: int = Field(..., ge=0, description="Sequential segment index.")
    text: str = Field(..., min_length=1, description="Transcribed utterance.")
    confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Backend confidence score when provided.",
    )
    language: Optional[str] = Field(
        None,
        min_length=1,
        description="ISO language code detected by the recogniser.",
    )
    started_at: float = Field(
        ..., ge=0.0, description="Unix timestamp when speech started."
    )
    ended_at: float = Field(
        ..., ge=0.0, description="Unix timestamp when speech ended."
    )
    latency_ms: Optional[float] = Field(
        None,
        ge=0.0,
        description="End-to-end latency the ASR observed for this segment.",
    )

    @model_validator(mode="after")
    def _validate_timestamps(self) -> "_ASREventBase":
        started_at = self.started_at
        ended_at = self.ended_at
        if started_at is not None and ended_at is not None and ended_at < started_at:
            raise ValueError("ended_at must be greater than or equal to started_at")
        return self


class ASRPartialEvent(_ASREventBase):
    """Streaming update emitted while speech is still ongoing."""

    type: Literal["asr_partial"] = Field(
        default="asr_partial",
        description="Event discriminator understood by the orchestrator.",
    )


class ASRFinalEvent(_ASREventBase):
    """Final event emitted once the ASR worker has completed a segment."""

    type: Literal["asr_final"] = Field(
        default="asr_final",
        description="Event discriminator understood by the orchestrator.",
    )
    duration_ms: Optional[float] = Field(
        None,
        ge=0.0,
        description="Total duration of the captured speech segment.",
    )


ASREventPayload = Union[ASRPartialEvent, ASRFinalEvent]


__all__ = ["ASRPartialEvent", "ASRFinalEvent", "ASREventPayload"]
