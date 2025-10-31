from __future__ import annotations

import re
import time
from collections import Counter
from typing import Iterable, List

from .ring_buffer import MemoryTurn
from .storage import MemorySummary

_STOP_WORDS = {
    "this",
    "that",
    "have",
    "with",
    "from",
    "about",
    "there",
    "their",
    "would",
    "could",
    "should",
    "because",
    "where",
    "which",
    "while",
    "really",
    "again",
    "doing",
    "being",
    "people",
    "thanks",
    "thank",
    "please",
}


class Summarizer:
    """Heuristic summarizer that keeps highlights and tone for the VTuber persona."""

    def __init__(self, strategy: str = "structured") -> None:
        self.strategy = strategy

    async def summarize(self, turns: Iterable[MemoryTurn]) -> MemorySummary:
        messages = list(turns)
        if not messages:
            return MemorySummary(
                summary_text="Awaiting first turns.",
                mood_state="kawaii",
                metadata={"chaos": 0.0, "energy": 0.3, "topics": []},
                ts=time.time(),
            )

        window = messages[-12:]
        exclamations = sum(turn.text.count("!") for turn in window)
        chaos_ratio = exclamations / max(len(window), 1)
        mood_state = "chaotic" if chaos_ratio > 0.55 else "kawaii"
        energy = min(1.0, 0.35 + chaos_ratio)

        user_turns: List[MemoryTurn] = [t for t in window if t.role == "user"]
        assistant_turns: List[MemoryTurn] = [
            t for t in window if t.role == "assistant"
        ]

        highlights: List[str] = []
        if user_turns:
            latest_user = user_turns[-1].text.strip()
            highlights.append(f"Viewer: {latest_user[:120]}")
            if len(user_turns) > 1:
                previous_user = user_turns[-2].text.strip()
                highlights.append(f"Earlier viewer line: {previous_user[:120]}")
        if assistant_turns:
            latest_bot = assistant_turns[-1].text.strip()
            highlights.append(f"Kitsu responded: {latest_bot[:120]}")

        words = re.findall(
            r"[A-Za-zÀ-ÖØ-öø-ÿ]{4,}",
            " ".join(turn.text for turn in window).lower(),
        )
        filtered_words = [word for word in words if word not in _STOP_WORDS]
        topics = [
            word
            for word, _ in Counter(filtered_words).most_common(4)
        ]

        if not highlights:
            highlights.append("Conversation is warming up.")

        summary_lines = ["Recent highlights:"]
        summary_lines.extend(f"- {item}" for item in highlights[:4])
        summary_text = "\n".join(summary_lines)

        metadata = {
            "chaos": round(chaos_ratio, 2),
            "energy": round(energy, 2),
            "topics": topics,
            "turns_considered": len(window),
        }

        return MemorySummary(
            summary_text=summary_text,
            mood_state=mood_state,
            metadata=metadata,
            ts=time.time(),
        )


__all__ = ["Summarizer"]
