"""Time source abstraction so token expiry and rate limiting are testable without sleeping."""

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current wall-clock time, timezone-aware UTC."""
        ...

    def monotonic(self) -> float:
        """Monotonic seconds for measuring intervals."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class ManualClock:
    """Deterministic clock that only moves when told to (tests, simulations)."""

    def __init__(self, start: datetime | None = None) -> None:
        start = start or datetime(2026, 1, 1, tzinfo=UTC)
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware")
        self._now = start.astimezone(UTC)
        self._monotonic = 0.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("a clock cannot go backwards")
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds
