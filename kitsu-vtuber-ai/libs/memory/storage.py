from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import aiosqlite


@dataclass
class MemorySummary:
    summary_text: str
    mood_state: str
    metadata: Dict[str, Any]
    ts: float
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "summary_text": self.summary_text,
            "mood_state": self.mood_state,
            "metadata": self.metadata,
            "ts": self.ts,
        }


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS mem_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    summary_text TEXT NOT NULL,
                    mood_state TEXT NOT NULL,
                    knobs TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def save_summary(self, summary: MemorySummary) -> MemorySummary:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "INSERT INTO mem_summaries (ts, summary_text, mood_state, knobs) VALUES (?, ?, ?, ?)",
                (
                    summary.ts,
                    summary.summary_text,
                    summary.mood_state,
                    json.dumps(summary.metadata),
                ),
            )
            await db.commit()
            summary.id = cursor.lastrowid
        return summary

    async def load_latest(self, max_age_seconds: float) -> Optional[MemorySummary]:
        cutoff = time.time() - max_age_seconds
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT id, ts, summary_text, mood_state, knobs FROM mem_summaries WHERE ts >= ? ORDER BY ts DESC LIMIT 1",
                (cutoff,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            metadata = json.loads(row["knobs"]) if row["knobs"] else {}
            return MemorySummary(
                id=row["id"],
                ts=row["ts"],
                summary_text=row["summary_text"],
                mood_state=row["mood_state"],
                metadata=metadata if isinstance(metadata, dict) else {},
            )
