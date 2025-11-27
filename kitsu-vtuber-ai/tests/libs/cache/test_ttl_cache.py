from __future__ import annotations

import time

from libs.cache import TTLCache


def test_ttl_cache_respects_lru_eviction() -> None:
    cache = TTLCache[str, int](max_entries=2, ttl_seconds=5.0)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1  # refresh LRU order
    cache.put("c", 3)
    assert cache.get("a") == 1
    assert cache.get("b") is None  # evicted
    assert cache.get("c") == 3


def test_ttl_cache_expires_entries() -> None:
    cache = TTLCache[str, int](max_entries=2, ttl_seconds=0.05)
    cache.put("a", 42)
    time.sleep(0.06)
    assert cache.get("a") is None
