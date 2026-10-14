"""In-memory fixed-window rate limiter with bounded memory."""

from ff_gateway.domain.clock import Clock


class RateLimiter:
    """Fixed window per key. Memory is bounded: expired keys are swept at most once per window and,
    if the table is still at ``max_keys``, the oldest-window keys are evicted (an evicted key just
    gets a fresh window - the limiter fails open for it rather than growing without bound)."""

    def __init__(self, clock: Clock, window_seconds: int = 60, max_keys: int = 50_000) -> None:
        self._clock, self._window, self._max = clock, window_seconds, max(1, max_keys)
        self._hits: dict[str, tuple[float, int]] = {}  # insertion order == window-start order
        self._last_sweep = clock.monotonic()

    def __len__(self) -> int:
        return len(self._hits)

    def _make_room(self, now: float) -> None:
        if now - self._last_sweep >= self._window or len(self._hits) >= self._max:
            self._hits = {k: v for k, v in self._hits.items() if now - v[0] < self._window}
            self._last_sweep = now
        while len(self._hits) >= self._max:
            del self._hits[next(iter(self._hits))]

    def check(self, key: str, limit: int) -> int | None:
        """Count a hit. Returns None if allowed, else seconds to wait."""
        now = self._clock.monotonic()
        entry = self._hits.get(key)
        if entry is not None and now - entry[0] >= self._window:
            del self._hits[key]  # re-inserted below so ordering stays by window start
            entry = None
        if entry is None:
            self._make_room(now)
            self._hits[key] = (now, 1)
            return None if limit > 0 else max(1, self._window)
        start, count = entry
        if count >= limit:
            return max(1, int(self._window - (now - start)) + 1)
        self._hits[key] = (start, count + 1)
        return None

    def blocked(self, key: str, limit: int) -> int | None:
        """Seconds to wait if ``key`` already used up ``limit`` hits in the current window (does not count)."""
        entry = self._hits.get(key)
        if entry is None:
            return None
        start, count = entry
        now = self._clock.monotonic()
        if now - start >= self._window or count < limit:
            return None
        return max(1, int(self._window - (now - start)) + 1)
