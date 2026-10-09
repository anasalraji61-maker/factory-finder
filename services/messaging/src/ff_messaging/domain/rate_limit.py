"""In-memory sliding-window rate limiter (per key, single process).

Good enough for one service instance; a Redis-backed limiter with the same ``hit`` signature
can replace it when the service is scaled horizontally.
"""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateDecision:
    allowed: bool
    remaining: int
    retry_after: float  # seconds until the next hit would be allowed (0 when allowed)


class SlidingWindowRateLimiter:
    def __init__(
        self,
        *,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 50_000,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.limit = limit
        self.window = float(window_seconds)
        self._clock = clock
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> RateDecision:
        """Record an attempt for ``key`` and say whether it is allowed."""
        now = self._clock()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self._max_keys:
                self._prune(now)
            hits = self._hits[key] = deque()
        cutoff = now - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            return RateDecision(allowed=False, remaining=0, retry_after=hits[0] + self.window - now)
        hits.append(now)
        return RateDecision(allowed=True, remaining=self.limit - len(hits), retry_after=0.0)

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        stale = [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for k in stale:
            del self._hits[k]
