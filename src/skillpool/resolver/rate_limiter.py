"""RateLimiter — sliding window rate limiter."""
from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    """Sliding window rate limiter.

    Usage:
        limiter = RateLimiter(max_requests=100, window_seconds=1.0)
        if limiter.allow():
            process_request()
        else:
            reject_with_429()
    """

    def __init__(self, max_requests: int = 100, window_seconds: float = 1.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: deque[float] = deque()

    def allow(self) -> bool:
        """Check if a request is allowed under the rate limit."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        # Remove expired timestamps
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()
        if len(self._timestamps) < self.max_requests:
            self._timestamps.append(now)
            return True
        return False

    @property
    def current_count(self) -> int:
        """Number of requests in the current window."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()
        return len(self._timestamps)

    def reset(self) -> None:
        """Reset the rate limiter."""
        self._timestamps.clear()
