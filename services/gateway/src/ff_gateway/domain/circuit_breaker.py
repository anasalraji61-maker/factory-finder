"""Per-upstream circuit breaker: closed -> (N consecutive failures) -> open -> (cooldown) -> half-open (one probe)."""

import logging
import math

from ff_gateway.domain.clock import Clock

log = logging.getLogger("ff_gateway")


class CircuitBreaker:
    def __init__(self, name: str, clock: Clock, threshold: int, cooldown: float) -> None:
        self.name, self._clock, self._threshold, self._cooldown = name, clock, threshold, cooldown
        self._failures = 0
        self._opened_at: float | None = None
        self._probing = False

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        return "half_open" if self._probing else "open"

    def before(self) -> int | None:
        """None = go ahead (in half-open state this caller is the single probe); else seconds until a retry makes sense."""
        if self._threshold <= 0 or self._opened_at is None:
            return None
        left = self._opened_at + self._cooldown - self._clock.monotonic()
        if left > 0:
            return max(1, math.ceil(left))
        if self._probing:
            return 1  # a probe is already in flight
        self._probing = True
        return None

    def success(self) -> None:
        if self._opened_at is not None:
            log.info("circuit closed upstream=%s", self.name)
        self._failures, self._opened_at, self._probing = 0, None, False

    def failure(self) -> None:
        if self._threshold <= 0:
            return
        self._failures += 1
        if self._probing or self._failures >= self._threshold:
            if self._opened_at is None or self._probing:
                log.warning("circuit open upstream=%s failures=%d", self.name, self._failures)
            self._opened_at, self._probing = self._clock.monotonic(), False

    def abort(self) -> None:
        """The call ended without a verdict (cancelled, gateway-side error): free the probe slot, no count."""
        self._probing = False


class BreakerRegistry:
    def __init__(self, clock: Clock, threshold: int, cooldown: float) -> None:
        self._clock, self._threshold, self._cooldown = clock, threshold, cooldown
        self._items: dict[str, CircuitBreaker] = {}

    def get(self, upstream: str) -> CircuitBreaker:
        b = self._items.get(upstream)
        if b is None:
            b = self._items[upstream] = CircuitBreaker(upstream, self._clock, self._threshold, self._cooldown)
        return b
