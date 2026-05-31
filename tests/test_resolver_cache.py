"""Tests for Resolver cache with TTL expiration."""
import time

from skillpool.resolver.cache import LRUCache


class TestLRUCacheBasic:
    def test_put_and_get(self) -> None:
        cache = LRUCache(max_size=10)
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_miss(self) -> None:
        cache = LRUCache()
        assert cache.get("nonexistent") is None

    def test_lru_eviction(self) -> None:
        cache = LRUCache(max_size=3)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        cache.put("d", 4)  # evicts "a"
        assert cache.get("a") is None
        assert cache.get("d") == 4

    def test_lru_access_reorders(self) -> None:
        cache = LRUCache(max_size=3)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        cache.get("a")  # access "a", moves to end
        cache.put("d", 4)  # evicts "b" (least recently used)
        assert cache.get("a") == 1
        assert cache.get("b") is None

    def test_overwrite_key(self) -> None:
        cache = LRUCache()
        cache.put("key", "old")
        cache.put("key", "new")
        assert cache.get("key") == "new"

    def test_invalidate(self) -> None:
        cache = LRUCache()
        cache.put("key", "value")
        assert cache.invalidate("key") is True
        assert cache.get("key") is None
        assert cache.invalidate("key") is False

    def test_clear(self) -> None:
        cache = LRUCache()
        cache.put("a", 1)
        cache.put("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.stats()["size"] == 0

    def test_stats(self) -> None:
        cache = LRUCache()
        cache.put("key", "value")
        cache.get("key")   # hit
        cache.get("miss")  # miss
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1


class TestLRUCacheTTL:
    def test_entry_not_expired(self) -> None:
        cache = LRUCache(ttl_seconds=10.0)
        cache.put("key", "value")
        assert cache.get("key") == "value"

    def test_entry_expired(self) -> None:
        cache = LRUCache(ttl_seconds=0.01)  # 10ms TTL
        cache.put("key", "value")
        time.sleep(0.02)
        assert cache.get("key") is None

    def test_expired_entry_evicted_on_get(self) -> None:
        cache = LRUCache(ttl_seconds=0.01)
        cache.put("key", "value")
        time.sleep(0.02)
        cache.get("key")  # triggers eviction
        assert cache.stats()["size"] == 0

    def test_per_entry_ttl_override(self) -> None:
        cache = LRUCache(ttl_seconds=10.0)
        cache.put("short", "value", ttl_seconds=0.01)
        cache.put("long", "value")
        time.sleep(0.02)
        assert cache.get("short") is None  # expired
        assert cache.get("long") == "value"  # still valid

    def test_is_expired(self) -> None:
        cache = LRUCache(ttl_seconds=0.01)
        cache.put("key", "value")
        assert cache.is_expired("key") is False
        time.sleep(0.02)
        assert cache.is_expired("key") is True

    def test_is_expired_nonexistent_key(self) -> None:
        cache = LRUCache()
        assert cache.is_expired("nonexistent") is False

    def test_ttl_expired_counts_as_miss(self) -> None:
        cache = LRUCache(ttl_seconds=0.01)
        cache.put("key", "value")
        time.sleep(0.02)
        cache.get("key")
        assert cache.stats()["misses"] == 1

    def test_refresh_ttl_on_overwrite(self) -> None:
        cache = LRUCache(ttl_seconds=0.02)
        cache.put("key", "v1")
        time.sleep(0.01)
        cache.put("key", "v2")  # refreshes TTL
        time.sleep(0.015)
        # v2 was put 15ms ago, TTL is 20ms → should still be valid
        assert cache.get("key") == "v2"
