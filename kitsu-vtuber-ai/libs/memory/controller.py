from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .ring_buffer import ConversationRingBuffer, MemoryTurn
from .storage import MemoryStore, MemorySummary
from .summarizer import Summarizer


class MemoryController:
    def __init__(
        self,
        *,
        buffer_size: int = 40,
        summary_interval: int = 6,
        database_path: Optional[Path] = None,
        store: Optional[MemoryStore] = None,
        summarizer: Optional[Summarizer] = None,
    ) -> None:
        self.buffer = ConversationRingBuffer(capacity=buffer_size)
        self.summary_interval = summary_interval
        self._count = 0
        self._summarizer = summarizer or Summarizer()
        db_path = database_path or Path(os.getenv("MEMORY_DB_PATH", "data/memory.sqlite3"))
        self._store = store or MemoryStore(db_path)
        self._lock = asyncio.Lock()
        self.current_summary: Optional[MemorySummary] = None
        self.restore_enabled = False

    async def prepare(self, restore: bool, max_age_seconds: float = 7200.0) -> Optional[MemorySummary]:
        await self._store.initialize()
        self.restore_enabled = restore
        if not restore:
            return None
        summary = await self._store.load_latest(max_age_seconds)
        self.current_summary = summary
        return summary

    async def add_turn(self, role: str, text: str) -> Optional[MemorySummary]:
        async with self._lock:
            self.buffer.append(MemoryTurn.create(role=role, text=text))
            self._count += 1
            if self._count < self.summary_interval:
                return None
            self._count = 0
            summary = await self._summarizer.summarize(self.buffer.as_list())
            saved = await self._store.save_summary(summary)
            self.current_summary = saved
            return saved

    def snapshot(self) -> Dict[str, Any]:
        return {
            "buffer_length": len(self.buffer),
            "summary_interval": self.summary_interval,
            "restore_enabled": self.restore_enabled,
            "current_summary": self.current_summary.to_dict() if self.current_summary else None,
        }

    async def reset(self) -> None:
        async with self._lock:
            self.buffer.clear()
            self._count = 0
            self.current_summary = None


__all__ = ["MemoryController", "MemorySummary", "ConversationRingBuffer", "MemoryTurn"]
