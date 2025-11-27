from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class PolicyRequestPayload(BaseModel):
    """Payload posted to the policy/LLM worker."""

    text: str = Field(..., min_length=1, description="User utterance to respond to.")
    is_final: bool = Field(
        True,
        description="Indicates whether this transcript is final (True) or a streaming partial (False).",
    )
    persona_style: str = Field("kawaii", description="Current persona style.")
    chaos_level: float = Field(0.35, ge=0.0, le=1.0)
    energy: float = Field(0.65, ge=0.0, le=1.0)
    family_friendly: Optional[bool] = Field(
        None, description="Override to toggle family-friendly safeguards."
    )
    persona_prompt: Optional[str] = Field(
        None,
        description="Optional system prompt template specific to the active persona.",
    )
    memory_summary: Optional[str] = Field(
        None, description="Short summary of recent conversation state."
    )
    recent_turns: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Conversation history in {'role','content'} format.",
    )

    @field_validator("recent_turns")
    @classmethod
    def _validate_turns(cls, value: List[Dict[str, str]]) -> List[Dict[str, str]]:
        validated: List[Dict[str, str]] = []
        for item in value:
            if "role" not in item or "content" not in item:
                raise ValueError("recent_turn items must include role and content")
            role = item["role"]
            if role not in {"user", "assistant", "system"}:
                raise ValueError(f"Invalid role in recent_turns: {role}")
            validated.append(item)
        return validated


__all__ = ["PolicyRequestPayload"]
