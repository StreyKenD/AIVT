from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from libs.safety import ModerationPipeline

from .ring_buffer import ConversationRingBuffer, MemoryTurn
from .storage import MemoryStore, MemorySummary
from .summarizer import Summarizer


logger = logging.getLogger(__name__)


class MemoryController:
    def __init__(
        self,
        *,
        buffer_size: int = 40,
        summary_interval: int = 6,
        database_path: Optional[Path] = None,
        history_path: Optional[Path] = None,
        summary_strategy: str = "structured",
        store: Optional[MemoryStore] = None,
        summarizer: Optional[Summarizer] = None,
        moderation: Optional[ModerationPipeline] = None,
    ) -> None:
        self.buffer = ConversationRingBuffer(capacity=buffer_size)
        self.summary_interval = max(1, summary_interval)
        self._count = 0
        self._summarizer = summarizer or Summarizer(strategy=summary_strategy)
        db_path = database_path or Path(
            os.getenv("MEMORY_DB_PATH", "data/memory.sqlite3")
        )
        self._store = store or MemoryStore(db_path)
        self._lock = asyncio.Lock()
        self.current_summary: Optional[MemorySummary] = None
        self.restore_enabled = False
        self._moderation = moderation or ModerationPipeline()
        self.history_path: Optional[Path] = history_path or Path(
            os.getenv("MEMORY_HISTORY_PATH", "data/memory_history.json")
        )
        self._history_enabled = self.history_path is not None
        if self._history_enabled and self.history_path is not None:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)

    async def prepare(
        self, restore: bool, max_age_seconds: float = 7200.0
    ) -> Optional[MemorySummary]:
        await self._store.initialize()
        self.restore_enabled = restore
        if restore:
            await self._load_history()
            summary = await self._store.load_latest(max_age_seconds)
            self.current_summary = summary
            return summary
        self.current_summary = None
        return None

    async def add_turn(self, role: str, text: str) -> Optional[MemorySummary]:
        async with self._lock:
            sanitized = await self._sanitize_text(text)
            self.buffer.append(MemoryTurn.create(role=role, text=sanitized))
            self._count += 1
            await self._persist_history()
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
            "current_summary": (
                self.current_summary.to_dict() if self.current_summary else None
            ),
            "history_path": (
                str(self.history_path)
                if self._history_enabled and self.history_path is not None
                else None
            ),
        }

    async def reset(self) -> None:
        async with self._lock:
            self.buffer.clear()
            self._count = 0
            self.current_summary = None
            if self._history_enabled and self.history_path is not None:
                with contextlib.suppress(OSError):
                    self.history_path.unlink()

    async def _persist_history(self) -> None:
        history_path = self.history_path
        if not self._history_enabled or history_path is None:
            return
        data = {"turns": [turn.to_dict() for turn in self.buffer.as_list()]}
        text = json.dumps(data, ensure_ascii=False, indent=2)
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, lambda: history_path.write_text(text, encoding="utf-8")
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("Failed to persist memory history: %s", exc)

    async def _load_history(self) -> None:
        history_path = self.history_path
        if not self._history_enabled or history_path is None:
            return
        loop = asyncio.get_running_loop()
        try:
            raw = await loop.run_in_executor(
                None, lambda: history_path.read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("Failed to read memory history: %s", exc)
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive guard
            logger.warning("Invalid memory history payload: %s", exc)
            return
        turns = payload.get("turns", [])
        for entry in turns[-self.buffer.capacity :]:
            try:
                self.buffer.append(MemoryTurn.from_dict(entry))
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.debug("Skipping malformed history entry: %s", exc)
        self._count = len(self.buffer) % self.summary_interval

    async def _sanitize_text(self, text: str) -> str:
        candidate = (text or "").strip()
        if not candidate:
            return ""
        if self._moderation is None:
            return candidate[:2000]
        result = await self._moderation.guard_response(candidate)
        sanitized = result.sanitized_text.strip()
        if not sanitized:
            sanitized = "[filtered]"
        return sanitized[:2000]


__all__ = ["MemoryController", "MemorySummary", "ConversationRingBuffer", "MemoryTurn"]
