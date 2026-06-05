"""Tests for RateLimiter — sliding window rate limiter."""

from skillpool.resolver.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_allows_under_limit(self) -> None:
        limiter = RateLimiter(max_requests=5, window_seconds=1.0)
        for _ in range(5):
            assert limiter.allow() is True

    def test_rejects_over_limit(self) -> None:
        limiter = RateLimiter(max_requests=3, window_seconds=1.0)
        for _ in range(3):
            limiter.allow()
        assert limiter.allow() is False

    def test_current_count(self) -> None:
        limiter = RateLimiter(max_requests=10, window_seconds=1.0)
        for _ in range(3):
            limiter.allow()
        assert limiter.current_count == 3

    def test_reset(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=1.0)
        limiter.allow()
        limiter.allow()
        limiter.reset()
        assert limiter.current_count == 0
        assert limiter.allow() is True

    def test_window_expiry(self) -> None:
        limiter = RateLimiter(max_requests=2, window_seconds=0.01)
        limiter.allow()
        limiter.allow()
        assert limiter.allow() is False
        import time
        time.sleep(0.02)
        assert limiter.allow() is True
