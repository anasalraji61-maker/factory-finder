"""Per-user daily request quota: UTC-day window, in-memory by default, Redis when configured."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ff_assistant.ratelimit import WindowLimiter

DAY = 86400
MAX_KEYS = 200_000  # per-day counter cap: spoofed ids/addresses cannot grow memory without bound


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_s: int


class BurstLimiter:
    """Per-minute sliding-window limiter (in memory, per process), keyed like :class:`DailyQuota`."""

    def __init__(self, per_user: int, per_anon: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_user, self.per_anon = per_user, per_anon
        self._lim = WindowLimiter(window_seconds=60, mode="sliding", clock=clock, max_keys=MAX_KEYS, on_full="closed")

    def hit(self, user_id: str | None, client: str = "unknown") -> QuotaDecision:
        limit = self.per_user if user_id else self.per_anon
        key = f"u:{user_id}" if user_id else f"a:{client}"
        d = self._lim.hit_sync(key, limit)
        return QuotaDecision(d.allowed, limit, d.remaining, int(d.retry_after) + 1 if not d.allowed else 0)


class DailyQuota:
    """``hit``/``usage``/``forget`` are the synchronous in-memory API (tests, single process);
    ``ahit``/``ausage``/``aforget`` use Redis (``redis`` client) when given, else the same memory counters."""

    def __init__(self, per_user: int, per_anon: int, clock: Callable[[], float] = time.time,
                 redis: Any = None, prefix: str = "ff:assistant:quota:") -> None:
        self.per_user, self.per_anon = per_user, per_anon
        # new keys beyond the cap are refused (fail closed); fixed counters reset at the UTC day boundary
        self._lim = WindowLimiter(window_seconds=DAY, mode="calendar", clock=clock, max_keys=MAX_KEYS,
                                  on_full="closed", redis=redis, prefix=prefix, on_error="memory")

    @staticmethod
    def _key(user_id: str | None, client: str) -> str:
        return f"u:{user_id}" if user_id else f"a:{client}"

    def _limit(self, user_id: str | None) -> int:
        return self.per_user if user_id else self.per_anon

    @staticmethod
    def _out(d, limit: int) -> QuotaDecision:
        return QuotaDecision(d.allowed, limit, d.remaining, int(d.retry_after) + 1 if not d.allowed else 0)

    def hit(self, user_id: str | None, client: str = "unknown") -> QuotaDecision:
        limit = self._limit(user_id)
        return self._out(self._lim.hit_sync(self._key(user_id, client), limit), limit)

    async def ahit(self, user_id: str | None, client: str = "unknown") -> QuotaDecision:
        limit = self._limit(user_id)
        return self._out(await self._lim.hit(self._key(user_id, client), limit), limit)

    def usage(self, user_id: str) -> int:
        """Requests counted for the user in the current UTC day window (0 if none)."""
        return self._lim.count_sync(f"u:{user_id}")

    async def ausage(self, user_id: str) -> int:
        return await self._lim.count(f"u:{user_id}")

    def forget(self, user_id: str) -> int:
        """Drop the user's counter (account erasure). Returns how many counters were removed."""
        return min(1, self._lim.reset_sync(f"u:{user_id}"))

    async def aforget(self, user_id: str) -> int:
        return min(1, await self._lim.reset(f"u:{user_id}"))
