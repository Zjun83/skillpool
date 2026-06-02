"""Resolver cache — LRU with TTL expiration and thread safety.

Each cache entry has a TTL (default 3600s). Entries past TTL are treated
as misses and lazily evicted on access.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CacheEntry:
    """A cached value with expiration timestamp."""
    value: Any
    expires_at: float  # time.monotonic() timestamp


class LRUCache:
    """LRU cache with TTL expiration and thread-safe operations.

    Args:
        max_size: Maximum number of entries.
        ttl_seconds: Time-to-live for each entry (default 3600s).
    """

    def __init__(self, max_size: int = 128, ttl_seconds: float = 3600.0) -> None:
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    @staticmethod
    def make_key(skill_ids: list[str], **kwargs: object) -> str:
        """Generate a deterministic cache key from skill_ids and kwargs."""
        payload = json.dumps({"ids": sorted(skill_ids), **kwargs}, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def get(self, key: str) -> Optional[Any]:
        """Get a cached value. Returns None on miss or TTL expiry."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            # Check TTL
            if time.monotonic() > entry.expires_at:
                del self._cache[key]
                self._misses += 1
                return None
            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return entry.value

    def put(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        """Store a value with optional per-entry TTL override."""
        with self._lock:
            ttl = ttl_seconds if ttl_seconds is not None else self._ttl_seconds
            entry = CacheEntry(value=value, expires_at=time.monotonic() + ttl)
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = entry
            # Evict oldest if over capacity
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self, key: str) -> bool:
        """Remove a specific key. Returns True if key existed."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all entries."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, int]:
        """Return cache hit/miss statistics."""
        with self._lock:
            return {"hits": self._hits, "misses": self._misses, "size": len(self._cache)}

    def is_expired(self, key: str) -> bool:
        """Check if a key exists but is expired (without evicting)."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            return time.monotonic() > entry.expires_at