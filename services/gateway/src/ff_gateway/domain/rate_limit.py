"""Rate-limit storage: a small interface, an in-memory default and an optional Redis backend."""

import logging
from itertools import islice
from typing import Any, Protocol

from ff_gateway.domain.clock import Clock

log = logging.getLogger("ff_gateway")


class LimitStore(Protocol):
    """Async fixed-window limiter. ``check`` counts a hit (None = allowed, else seconds to wait);
    ``blocked`` only peeks."""

    async def check(self, key: str, limit: int) -> int | None: ...

    async def blocked(self, key: str, limit: int) -> int | None: ...


class RateLimiter:
    """In-memory store (default). Fixed window per key. Memory is bounded: expired keys are popped from the front when room is needed and,
    if the table is still at ``max_keys``, a batch (1%) of the oldest-window keys is evicted (an evicted key just
    gets a fresh window - the limiter fails open for it rather than growing without bound)."""

    def __init__(self, clock: Clock, window_seconds: int = 60, max_keys: int = 50_000) -> None:
        self._clock, self._window, self._max = clock, window_seconds, max(1, max_keys)
        self._hits: dict[str, tuple[float, int]] = {}  # insertion order == window-start order
        self._last_sweep = clock.monotonic()

    def __len__(self) -> int:
        return len(self._hits)

    def _make_room(self, now: float) -> None:
        """Amortized O(1): ``_hits`` is ordered by window start, so expired keys are a prefix that is popped
        (each key is popped once). If the table is still full of live keys, evict a small batch of the oldest so
        the next hits do not each pay for eviction."""
        hits = self._hits
        while hits:
            oldest = next(iter(hits))
            if now - hits[oldest][0] < self._window:
                break
            del hits[oldest]
        self._last_sweep = now
        if len(hits) >= self._max:
            for k in list(islice(hits, max(1, self._max // 100))):
                del hits[k]

    def check_sync(self, key: str, limit: int) -> int | None:
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

    def blocked_sync(self, key: str, limit: int) -> int | None:
        """Seconds to wait if ``key`` already used up ``limit`` hits in the current window (does not count)."""
        entry = self._hits.get(key)
        if entry is None:
            return None
        start, count = entry
        now = self._clock.monotonic()
        if now - start >= self._window or count < limit:
            return None
        return max(1, int(self._window - (now - start)) + 1)

    # LimitStore (async) face; the sync methods stay for direct use and tests
    async def check(self, key: str, limit: int) -> int | None:
        return self.check_sync(key, limit)

    async def blocked(self, key: str, limit: int) -> int | None:
        return self.blocked_sync(key, limit)


class RedisRateLimiter:
    """Shared fixed-window counters in Redis (INCR + EXPIRE); ``client`` is a ``redis.asyncio`` client
    (or any object with async incr/expire/ttl/get). Keys are namespaced so one Redis can serve many apps."""

    def __init__(self, client: Any, window_seconds: int = 60, prefix: str = "ff:gw:rl:") -> None:
        self._r, self._window, self._prefix = client, window_seconds, prefix

    async def check(self, key: str, limit: int) -> int | None:
        k = self._prefix + key
        n = int(await self._r.incr(k))
        ttl = int(await self._r.ttl(k))
        if n == 1 or ttl < 0:  # first hit, or a key left without expiry by a crash between INCR and EXPIRE
            await self._r.expire(k, self._window)
            ttl = self._window
        if n > max(limit, 0):
            return max(1, ttl + 1)
        return None

    async def blocked(self, key: str, limit: int) -> int | None:
        k = self._prefix + key
        raw = await self._r.get(k)
        if raw is None or int(raw) < limit:
            return None
        return max(1, int(await self._r.ttl(k)) + 1)


class FallbackLimiter:
    """Primary store with an in-memory fallback: if the primary raises (Redis down) the request is
    counted in memory instead (per process) and a warning is logged once per outage."""

    def __init__(self, primary: LimitStore, fallback: LimitStore) -> None:
        self._primary, self._fallback, self._degraded = primary, fallback, False

    def _fail(self, e: Exception) -> None:
        if not self._degraded:
            log.warning("rate-limit backend unavailable (%s); using in-memory limits", type(e).__name__)
        self._degraded = True

    async def check(self, key: str, limit: int) -> int | None:
        try:
            r = await self._primary.check(key, limit)
            self._degraded = False
            return r
        except Exception as e:
            self._fail(e)
            return await self._fallback.check(key, limit)

    async def blocked(self, key: str, limit: int) -> int | None:
        try:
            return await self._primary.blocked(key, limit)
        except Exception as e:
            self._fail(e)
            return await self._fallback.blocked(key, limit)


def make_redis_client(redis_url: str | None) -> Any:
    """One shared ``redis.asyncio`` client for every Redis-backed store, or None (no URL / library missing)."""
    if not redis_url:
        return None
    try:
        from redis.asyncio import Redis  # lazy: optional dependency (extra "redis")

        return Redis.from_url(redis_url, socket_connect_timeout=1.0, socket_timeout=1.0, decode_responses=True)
    except Exception as e:
        log.warning("Redis URL set but Redis is unusable (%s); using in-memory stores", type(e).__name__)
        return None


def build_limit_store(
    clock: Clock, max_keys: int, redis_url: str | None = None, redis_client: Any = None
) -> LimitStore:
    """Memory by default. With ``redis_url`` (or an injected client) use Redis, falling back to memory
    (with a warning) if the library is missing or the server is unreachable."""
    memory = RateLimiter(clock, max_keys=max_keys)
    if redis_client is None and not redis_url:
        return memory
    if redis_client is None:
        try:
            from redis.asyncio import Redis  # lazy: optional dependency (extra "redis")

            redis_client = Redis.from_url(
                redis_url, socket_connect_timeout=1.0, socket_timeout=1.0, decode_responses=True
            )
        except Exception as e:
            log.warning("FF_GATEWAY_REDIS_URL set but Redis is unusable (%s); using in-memory rate limits", type(e).__name__)
            return memory
    return FallbackLimiter(RedisRateLimiter(redis_client), memory)
