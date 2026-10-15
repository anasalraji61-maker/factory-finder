"""Per-user daily request quota (in-memory, per process, UTC day window, injectable clock)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

DAY = 86400
MAX_KEYS = 200_000  # per-day counter cap: spoofed ids/addresses cannot grow memory without bound


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_s: int


class DailyQuota:
    def __init__(self, per_user: int, per_anon: int, clock: Callable[[], float] = time.time) -> None:
        self.per_user, self.per_anon, self._clock = per_user, per_anon, clock
        self._day = -1
        self._counts: dict[str, int] = {}

    def hit(self, user_id: str | None, client: str = "unknown") -> QuotaDecision:
        now = self._clock()
        day = int(now // DAY)
        if day != self._day:  # new window: drop every counter (bounded memory)
            self._day, self._counts = day, {}
        key, limit = (f"u:{user_id}", self.per_user) if user_id else (f"a:{client}", self.per_anon)
        used = self._counts.get(key, 0)
        if key not in self._counts and len(self._counts) >= MAX_KEYS:
            return QuotaDecision(False, limit, 0, int((day + 1) * DAY - now) + 1)  # fail closed
        retry = int((day + 1) * DAY - now) + 1
        if used >= limit:
            return QuotaDecision(False, limit, 0, retry)
        self._counts[key] = used + 1
        return QuotaDecision(True, limit, limit - used - 1, retry)

    def usage(self, user_id: str) -> int:
        """Requests counted for the user in the current UTC day window (0 if none)."""
        if int(self._clock() // DAY) != self._day:
            return 0
        return self._counts.get(f"u:{user_id}", 0)

    def forget(self, user_id: str) -> int:
        """Drop the user's counter (account erasure). Returns how many counters were removed."""
        return 1 if self._counts.pop(f"u:{user_id}", None) is not None else 0
