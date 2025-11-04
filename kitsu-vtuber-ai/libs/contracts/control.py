from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class PersonaUpdateCommand(BaseModel):
    style: Optional[str] = Field(
        None, description="Persona style identifier, e.g. kawaii or chaotic."
    )
    chaos_level: Optional[float] = Field(None, ge=0.0, le=1.0)
    energy: Optional[float] = Field(None, ge=0.0, le=1.0)
    family_mode: Optional[bool] = Field(
        None, description="Family-friendly moderation flag."
    )
    preset: Optional[str] = Field(
        None, description="Optional persona preset identifier to apply."
    )
    system_message: Optional[str] = Field(
        None,
        description="Optional system turn to append when applying the update.",
    )


class ModuleToggleCommand(BaseModel):
    enabled: bool = Field(..., description="Desired enablement state for the module.")


class OBSSceneCommand(BaseModel):
    scene: str = Field(..., min_length=1, description="Target OBS scene name.")


class VTSExpressionCommand(BaseModel):
    expression: str = Field(
        ..., min_length=1, description="Target VTube Studio expression identifier."
    )
    intensity: Optional[float] = Field(
        0.6, ge=0.0, le=1.0, description="Expression intensity between 0 and 1."
    )


class ChatIngestCommand(BaseModel):
    role: str = Field(
        "user",
        description="Speaker role for memory context (user|assistant|system).",
    )
    text: str = Field(..., min_length=1, description="Original chat message.")

    @field_validator("role")
    @classmethod
    def _validate_role(cls, value: str) -> str:
        allowed = {"user", "assistant", "system"}
        if value not in allowed:
            raise ValueError("Invalid speaker role")
        return value


class PanicRequest(BaseModel):
    reason: Optional[str] = Field(
        None,
        description="Optional reason for triggering panic.",
        max_length=240,
    )


class MuteRequest(BaseModel):
    muted: bool = Field(..., description="Indicates whether the TTS worker is muted.")


class ResumeRequest(BaseModel):
    clear_mute: bool = Field(
        True,
        description="When true the resume action also unmutes the TTS worker.",
    )
    note: Optional[str] = Field(
        None,
        max_length=240,
        description="Optional operator note describing the resume action.",
    )


class PresetCommand(BaseModel):
    preset: str = Field(..., min_length=1, description="Preset identifier to apply.")


__all__ = [
    "ChatIngestCommand",
    "ModuleToggleCommand",
    "MuteRequest",
    "OBSSceneCommand",
    "PanicRequest",
    "PersonaUpdateCommand",
    "ResumeRequest",
    "PresetCommand",
    "VTSExpressionCommand",
]

# Backwards compatibility aliases (scheduled for removal).
PanicCommand = PanicRequest
MuteCommand = MuteRequest
