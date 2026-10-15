"""Window rate limiter: in-memory by default, shared via Redis when a client/URL is supplied.

Self-contained on purpose (stdlib only; ``redis`` is imported lazily). This file is the canonical
source; services that cannot depend on another package at build time (their Docker image and CI job
only contain ``services/<name>``) carry a byte-identical copy as ``ratelimit.py`` - a test in
``packages/py-common/tests`` fails if a copy drifts.

Modes (``mode``):
  sliding   exact sliding window in memory. On Redis it degrades to a fixed window (INCR + EXPIRE).
  fixed     window starts at the key's first hit.
  calendar  windows aligned to multiples of ``window_seconds`` of the wall clock (86400 = UTC day).

Failure policy (``on_error``) when Redis raises: ``memory`` (default; count in-process, warn once per
outage), ``open`` (allow) or ``closed`` (deny). Memory is bounded by ``max_keys``; when full, stale
keys are swept and then ``on_full`` decides: ``evict`` the oldest key (fails open for it) or
``closed`` (deny new keys, existing keys keep working).
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

log = logging.getLogger("ff_ratelimit")

Mode = Literal["sliding", "fixed", "calendar"]


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: float  # seconds until a hit would be allowed again (0.0 when allowed)


class MemoryWindows:
    """Single-process counters (the default backend)."""

    def __init__(self, *, window_seconds: float, mode: Mode, clock: Callable[[], float],
                 max_keys: int, on_full: Literal["evict", "closed"]) -> None:
        self.window, self.mode, self._clock = float(window_seconds), mode, clock
        self._max, self._on_full = max(1, max_keys), on_full
        self._sliding: dict[str, deque[float]] = {}
        self._fixed: dict[str, list[float]] = {}  # key -> [window_start, count]; insertion order == age
        self._last_sweep = clock()

    def __len__(self) -> int:
        return len(self._sliding) + len(self._fixed)

    def _start(self, now: float) -> float:
        return math.floor(now / self.window) * self.window if self.mode == "calendar" else now

    def _sweep(self, now: float) -> None:
        cutoff = now - self.window
        self._sliding = {k: v for k, v in self._sliding.items() if v and v[-1] > cutoff}
        self._fixed = {k: v for k, v in self._fixed.items() if v[0] > cutoff}
        self._last_sweep = now

    def _room(self, now: float) -> bool:
        if now - self._last_sweep >= self.window or len(self) >= self._max:
            self._sweep(now)
        if len(self) < self._max:
            return True
        if self._on_full == "closed":
            return False
        t = self._sliding if self.mode == "sliding" else self._fixed
        if t:
            del t[next(iter(t))]
        return True

    def hit(self, key: str, limit: int) -> Decision:
        now = self._clock()
        if limit < 1:
            return Decision(False, limit, 0, self.window)
        if self.mode == "sliding":
            hits = self._sliding.get(key)
            if hits is None:
                if not self._room(now):
                    return Decision(False, limit, 0, self.window)
                hits = self._sliding[key] = deque()
            cutoff = now - self.window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return Decision(False, limit, 0, hits[0] + self.window - now)
            hits.append(now)
            return Decision(True, limit, limit - len(hits), 0.0)
        st = self._fixed.get(key)
        if st is not None and now - st[0] >= self.window:
            del self._fixed[key]
            st = None
        if st is None:
            if not self._room(now):
                return Decision(False, limit, 0, self._start(now) + self.window - now)
            self._fixed[key] = [self._start(now), 1]
            return Decision(True, limit, limit - 1, 0.0)
        if st[1] >= limit:
            return Decision(False, limit, 0, st[0] + self.window - now)
        st[1] += 1
        return Decision(True, limit, int(limit - st[1]), 0.0)

    def count(self, key: str) -> int:
        now = self._clock()
        if self.mode == "sliding":
            hits = self._sliding.get(key)
            return sum(1 for t in hits if t > now - self.window) if hits else 0
        st = self._fixed.get(key)
        return int(st[1]) if st is not None and now - st[0] < self.window else 0

    def reset(self, key: str | None = None) -> int:
        if key is None:
            n = len(self)
            self._sliding.clear()
            self._fixed.clear()
            return n
        return int(self._sliding.pop(key, None) is not None) + int(self._fixed.pop(key, None) is not None)


class WindowLimiter:
    """``await limiter.hit(key)`` -> :class:`Decision`. ``hit_sync`` / ``count_sync`` / ``reset_sync``
    use the in-memory counters only (tests, single-process callers)."""

    def __init__(self, *, limit: int | None = None, window_seconds: float, mode: Mode = "sliding",
                 clock: Callable[[], float] | None = None, max_keys: int = 50_000,
                 on_full: Literal["evict", "closed"] = "evict", redis: Any = None,
                 prefix: str = "ff:rl:", on_error: Literal["memory", "open", "closed"] = "memory") -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        self.limit, self.window, self.mode = limit, float(window_seconds), mode
        self._clock = clock or (time.time if mode == "calendar" else time.monotonic)
        self.memory = MemoryWindows(window_seconds=window_seconds, mode=mode, clock=self._clock,
                                    max_keys=max_keys, on_full=on_full)
        self._redis, self._prefix, self._on_error, self._degraded = redis, prefix, on_error, False

    def _limit(self, limit: int | None) -> int:
        eff = self.limit if limit is None else limit
        if eff is None:
            raise ValueError("limit not configured")
        return eff

    # --- sync (memory only)
    def hit_sync(self, key: str, limit: int | None = None) -> Decision:
        return self.memory.hit(key, self._limit(limit))

    def count_sync(self, key: str) -> int:
        return self.memory.count(key)

    def reset_sync(self, key: str | None = None) -> int:
        return self.memory.reset(key)

    # --- async (Redis when configured)
    def _rkey(self, key: str, now: float) -> tuple[str, int, float | None]:
        """(redis key, ttl seconds, seconds-to-window-end if known from the clock)."""
        if self.mode == "calendar":
            wid = math.floor(now / self.window)
            left = (wid + 1) * self.window - now
            return f"{self._prefix}{key}:{wid}", math.ceil(left) + 1, left
        return self._prefix + key, math.ceil(self.window), None

    def _failed(self, exc: Exception) -> None:
        if not self._degraded:
            log.warning("rate-limit backend unavailable (%s); policy=%s", type(exc).__name__, self._on_error)
        self._degraded = True

    async def hit(self, key: str, limit: int | None = None) -> Decision:
        eff = self._limit(limit)
        if self._redis is None:
            return self.memory.hit(key, eff)
        try:
            now = self._clock()
            rk, ttl_s, left = self._rkey(key, now)
            n = int(await self._redis.incr(rk))
            if n == 1:
                await self._redis.expire(rk, ttl_s)
                ttl = ttl_s
            else:
                ttl = int(await self._redis.ttl(rk))
                if ttl < 0:  # crash between INCR and EXPIRE left no expiry
                    await self._redis.expire(rk, ttl_s)
                    ttl = ttl_s
            self._degraded = False
            if n > eff:
                return Decision(False, eff, 0, left if left is not None else float(max(1, ttl)))
            return Decision(True, eff, max(0, eff - n), 0.0)
        except Exception as exc:
            self._failed(exc)
            if self._on_error == "memory":
                return self.memory.hit(key, eff)
            if self._on_error == "open":
                return Decision(True, eff, eff, 0.0)
            return Decision(False, eff, 0, self.window)

    async def count(self, key: str) -> int:
        if self._redis is None:
            return self.memory.count(key)
        try:
            raw = await self._redis.get(self._rkey(key, self._clock())[0])
            return int(raw) if raw is not None else 0
        except Exception as exc:
            self._failed(exc)
            return self.memory.count(key)

    async def reset(self, key: str) -> int:
        """Forget ``key`` (current window). Returns how many counters were removed."""
        removed = self.memory.reset(key)
        if self._redis is not None:
            try:
                removed += int(await self._redis.delete(self._rkey(key, self._clock())[0]))
            except Exception as exc:
                self._failed(exc)
        return removed


def make_redis_client(url: str | None) -> Any:
    """``redis.asyncio`` client for ``url`` (short timeouts), or None if no URL / library missing."""
    if not url:
        return None
    try:
        from redis.asyncio import Redis  # optional dependency (extra "redis")

        return Redis.from_url(url, socket_connect_timeout=1.0, socket_timeout=1.0, decode_responses=True)
    except Exception as exc:
        log.warning("FF_REDIS_URL set but Redis is unusable (%s); using in-memory rate limits", type(exc).__name__)
        return None
