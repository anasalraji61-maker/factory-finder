"""Short-lived single-use WebSocket tickets (keeps the access token out of URLs / access logs)."""

import secrets
from collections import OrderedDict


class WsTicketStore:
    def __init__(self, clock, ttl_seconds: int = 30, max_items: int = 10_000) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._max = max(1, max_items)
        self._items: OrderedDict[str, tuple[str, float]] = OrderedDict()

    def _sweep(self, now: float) -> None:
        while self._items:
            key, (_, exp) = next(iter(self._items.items()))
            if exp > now:
                break
            self._items.pop(key)

    def issue(self, user_id: str) -> tuple[str, int]:
        now = self._clock.monotonic()
        self._sweep(now)
        while len(self._items) >= self._max:
            self._items.popitem(last=False)  # oldest first
        ticket = "wst_" + secrets.token_urlsafe(24)
        self._items[ticket] = (user_id, now + self._ttl)
        return ticket, self._ttl

    def consume(self, ticket: str) -> str | None:
        """User id for a valid ticket; the ticket is burned either way."""
        item = self._items.pop(ticket, None)
        if item is None:
            return None
        user_id, exp = item
        return user_id if exp > self._clock.monotonic() else None
