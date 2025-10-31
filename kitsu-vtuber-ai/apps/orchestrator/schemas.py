from __future__ import annotations

from pydantic import BaseModel, Field


class ManualChatRequest(BaseModel):
    text: str = Field(..., min_length=1, description="User message to send to the AI.")
    play_tts: bool = Field(
        True,
        description="Whether the orchestrator should trigger TTS playback for the response.",
    )


__all__ = ["ManualChatRequest"]
