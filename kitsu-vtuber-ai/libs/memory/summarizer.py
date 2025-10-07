from __future__ import annotations

import time
from typing import Iterable

from .ring_buffer import MemoryTurn
from .storage import MemorySummary


class Summarizer:
    """Synthetic summarizer used until an LLM is plugged in."""

    async def summarize(self, turns: Iterable[MemoryTurn]) -> MemorySummary:
        messages = list(turns)
        joined = " ".join(turn.text for turn in messages[-6:])
        exclamations = sum(turn.text.count("!") for turn in messages)
        chaos_ratio = exclamations / max(len(messages), 1)
        mood_state = "chaotic" if chaos_ratio > 0.6 else "kawaii"
        energy = min(1.0, 0.3 + chaos_ratio)
        knobs = {"chaos": round(chaos_ratio, 2), "energy": round(energy, 2)}
        summary_text = joined[:400] if joined else "Awaiting first turns."
        return MemorySummary(
            summary_text=summary_text,
            mood_state=mood_state,
            knobs=knobs,
            ts=time.time(),
        )
