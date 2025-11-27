from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Generic, Hashable, Optional, TypeVar


K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


@dataclass
class CacheEntry(Generic[V]):
    value: V
    expires_at: float


class TTLCache(Generic[K, V]):
    """Simple in-memory LRU cache with TTL semantics."""

    def __init__(self, *, max_entries: int = 128, ttl_seconds: float = 300.0) -> None:
        self._max_entries = max(1, int(max_entries))
        self._ttl = max(1.0, float(ttl_seconds))
        self._store: "OrderedDict[K, CacheEntry[V]]" = OrderedDict()

    def get(self, key: K) -> Optional[V]:
        entry = self._store.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.time():
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key, last=True)
        return entry.value

    def put(self, key: K, value: V) -> None:
        expires = time.time() + self._ttl
        self._store[key] = CacheEntry(value=value, expires_at=expires)
        self._store.move_to_end(key, last=True)
        while len(self._store) > self._max_entries:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()


__all__ = ["TTLCache"]
