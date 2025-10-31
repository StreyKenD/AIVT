from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Iterable, List


@dataclass
class MemoryTurn:
    role: str
    text: str
    ts: float

    @classmethod
    def create(cls, role: str, text: str) -> "MemoryTurn":
        return cls(role=role, text=text, ts=time.time())

    def to_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "text": self.text, "ts": self.ts}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryTurn":
        return cls(
            role=data.get("role", "user"),
            text=str(data.get("text", "")),
            ts=float(data.get("ts", time.time())),
        )


class ConversationRingBuffer:
    def __init__(self, capacity: int = 40) -> None:
        self.capacity = capacity
        self._buffer: Deque[MemoryTurn] = deque(maxlen=capacity)

    def append(self, turn: MemoryTurn) -> None:
        self._buffer.append(turn)

    def clear(self) -> None:
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)

    def as_list(self) -> List[MemoryTurn]:
        return list(self._buffer)

    def __iter__(self) -> Iterable[MemoryTurn]:
        return iter(self._buffer)
