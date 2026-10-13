"""In-memory fixed-window rate limiter."""

from ff_gateway.domain.clock import Clock


class RateLimiter:
    def __init__(self, clock: Clock, window_seconds: int = 60) -> None:
        self._clock, self._window = clock, window_seconds
        self._hits: dict[str, tuple[float, int]] = {}

    def check(self, key: str, limit: int) -> int | None:
        """Count a hit. Returns None if allowed, else seconds to wait."""
        now = self._clock.monotonic()
        start, count = self._hits.get(key, (now, 0))
        if now - start >= self._window:
            start, count = now, 0
        if count >= limit:
            return max(1, int(self._window - (now - start)) + 1)
        self._hits[key] = (start, count + 1)
        if len(self._hits) > 50_000:
            self._hits = {k: v for k, v in self._hits.items() if now - v[0] < self._window}
        return None
