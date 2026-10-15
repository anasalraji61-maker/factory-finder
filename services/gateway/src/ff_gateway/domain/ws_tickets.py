"""Short-lived single-use WebSocket tickets (keeps the access token out of URLs / access logs) and the
per-user open-socket counters. Both have an in-memory default and an optional Redis backend (same pattern as
``rate_limit.LimitStore``) so that several gateway replicas can share them."""

import logging
import secrets
from collections import OrderedDict
from typing import Any, Protocol

log = logging.getLogger("ff_gateway")


class TicketStore(Protocol):
    async def issue(self, user_id: str) -> tuple[str, int]: ...

    async def consume(self, ticket: str) -> str | None: ...


class WsTicketStore:
    """In-memory store (default, per process)."""

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

    def issue_sync(self, user_id: str) -> tuple[str, int]:
        now = self._clock.monotonic()
        self._sweep(now)
        while len(self._items) >= self._max:
            self._items.popitem(last=False)  # oldest first
        ticket = "wst_" + secrets.token_urlsafe(24)
        self._items[ticket] = (user_id, now + self._ttl)
        return ticket, self._ttl

    def consume_sync(self, ticket: str) -> str | None:
        """User id for a valid ticket; the ticket is burned either way."""
        item = self._items.pop(ticket, None)
        if item is None:
            return None
        user_id, exp = item
        return user_id if exp > self._clock.monotonic() else None

    def purge_user(self, user_id: str) -> int:
        """Drop every outstanding ticket of one user (account deletion / deactivation)."""
        dead = [t for t, (u, _) in self._items.items() if u == user_id]
        for t in dead:
            self._items.pop(t, None)
        return len(dead)

    async def issue(self, user_id: str) -> tuple[str, int]:
        return self.issue_sync(user_id)

    async def consume(self, ticket: str) -> str | None:
        return self.consume_sync(ticket)


class RedisWsTicketStore:
    """``SET key user EX ttl`` / ``GETDEL`` (single use even across replicas). Needs Redis >= 6.2.
    ``client`` is a ``redis.asyncio`` client (decode_responses=True) or anything with async set/getdel."""

    def __init__(self, client: Any, ttl_seconds: int = 30, prefix: str = "ff:gw:wst:") -> None:
        self._r, self._ttl, self._prefix = client, max(1, ttl_seconds), prefix

    async def issue(self, user_id: str) -> tuple[str, int]:
        ticket = "wst_" + secrets.token_urlsafe(24)
        await self._r.set(self._prefix + ticket, user_id, ex=self._ttl)
        return ticket, self._ttl

    async def consume(self, ticket: str) -> str | None:
        raw = await self._r.getdel(self._prefix + ticket)
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else str(raw)


class FallbackTicketStore:
    """Redis first; if it raises (outage) tickets are issued in memory instead (valid on this replica only) and a
    warning is logged once per outage. ``consume`` also checks memory so tickets issued during an outage still work."""

    def __init__(self, primary: TicketStore, fallback: WsTicketStore) -> None:
        self._primary, self._fallback, self._degraded = primary, fallback, False

    def _fail(self, e: Exception) -> None:
        if not self._degraded:
            log.warning("ws-ticket backend unavailable (%s); using in-memory tickets", type(e).__name__)
        self._degraded = True

    def purge_user(self, user_id: str) -> int:
        return self._fallback.purge_user(user_id)

    async def issue(self, user_id: str) -> tuple[str, int]:
        try:
            r = await self._primary.issue(user_id)
            self._degraded = False
            return r
        except Exception as e:
            self._fail(e)
            return self._fallback.issue_sync(user_id)

    async def consume(self, ticket: str) -> str | None:
        local = self._fallback.consume_sync(ticket)  # burns a local ticket either way
        try:
            remote = await self._primary.consume(ticket)
        except Exception as e:
            self._fail(e)
            remote = None
        return remote or local


class Lease(Protocol):
    async def release(self) -> None: ...


class ConnectionCounter(Protocol):
    """Per-user open-socket counter. ``acquire`` returns a lease (call ``release`` exactly once) or None when the
    cap is reached. ``cap <= 0`` means unlimited (still counted)."""

    async def acquire(self, user_id: str, cap: int) -> Lease | None: ...


class _MemoryLease:
    def __init__(self, counter: "MemoryConnectionCounter", user_id: str) -> None:
        self._c, self._u, self._done = counter, user_id, False

    async def release(self) -> None:
        if self._done:
            return
        self._done = True
        n = self._c.counts.get(self._u, 0)
        if n <= 1:
            self._c.counts.pop(self._u, None)
        else:
            self._c.counts[self._u] = n - 1


class MemoryConnectionCounter:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}  # user_id -> open proxied websockets (this process)

    async def acquire(self, user_id: str, cap: int) -> Lease | None:
        if cap > 0 and self.counts.get(user_id, 0) >= cap:
            return None
        self.counts[user_id] = self.counts.get(user_id, 0) + 1
        return _MemoryLease(self, user_id)


class _RedisLease:
    def __init__(self, counter: "RedisConnectionCounter", key: str) -> None:
        self._c, self._k, self._done = counter, key, False

    async def release(self) -> None:
        if self._done:
            return
        self._done = True
        try:
            n = int(await self._c._r.decr(self._k))
            if n <= 0:
                await self._c._r.delete(self._k)
        except Exception as e:  # key expires on its own (safety TTL)
            log.warning("ws-connection counter release failed (%s)", type(e).__name__)


class RedisConnectionCounter:
    """INCR/DECR per user. The key carries a safety TTL (refreshed on every acquire) so that a crashed replica cannot
    pin a user at the cap forever; a socket held open longer than ``ttl`` without any new connect may be forgotten."""

    def __init__(self, client: Any, ttl_seconds: int = 6 * 3600, prefix: str = "ff:gw:wsc:") -> None:
        self._r, self._ttl, self._prefix = client, ttl_seconds, prefix

    async def acquire(self, user_id: str, cap: int) -> Lease | None:
        key = self._prefix + user_id
        n = int(await self._r.incr(key))
        await self._r.expire(key, self._ttl)
        if cap > 0 and n > cap:
            await self._r.decr(key)
            return None
        return _RedisLease(self, key)


class FallbackConnectionCounter:
    def __init__(self, primary: ConnectionCounter, fallback: MemoryConnectionCounter) -> None:
        self._primary, self._fallback, self._degraded = primary, fallback, False

    async def acquire(self, user_id: str, cap: int) -> Lease | None:
        try:
            r = await self._primary.acquire(user_id, cap)
            self._degraded = False
            return r
        except Exception as e:
            if not self._degraded:
                log.warning("ws-connection backend unavailable (%s); counting in memory", type(e).__name__)
            self._degraded = True
            return await self._fallback.acquire(user_id, cap)


def build_ws_stores(
    clock, ttl_seconds: int, max_items: int, redis_client: Any = None
) -> tuple[TicketStore, ConnectionCounter, MemoryConnectionCounter]:
    """Memory by default; with a Redis client the shared backends wrapped with an in-memory fallback.
    Returns (tickets, connection counter, the in-memory counter)."""
    mem_tickets = WsTicketStore(clock, ttl_seconds, max_items)
    mem_counter = MemoryConnectionCounter()
    if redis_client is None:
        return mem_tickets, mem_counter, mem_counter
    return (
        FallbackTicketStore(RedisWsTicketStore(redis_client, ttl_seconds), mem_tickets),
        FallbackConnectionCounter(RedisConnectionCounter(redis_client), mem_counter),
        mem_counter,
    )
