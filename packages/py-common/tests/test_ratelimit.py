from pathlib import Path

import pytest

from ff_common.ratelimit import Decision, WindowLimiter, make_redis_client


class Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class FakeRedis:
    """Minimal async stand-in for redis.asyncio (no network). TTLs follow the injected clock."""

    def __init__(self, clock: Clock, fail: bool = False) -> None:
        self.clock, self.fail, self.data, self.exp = clock, fail, {}, {}

    def _alive(self, k):
        if k in self.exp and self.exp[k] <= self.clock.t:
            self.data.pop(k, None)
            self.exp.pop(k, None)

    async def incr(self, k):
        if self.fail:
            raise ConnectionError("down")
        self._alive(k)
        self.data[k] = self.data.get(k, 0) + 1
        return self.data[k]

    async def expire(self, k, s):
        self.exp[k] = self.clock.t + s

    async def ttl(self, k):
        self._alive(k)
        if k not in self.data:
            return -2
        return int(self.exp[k] - self.clock.t) if k in self.exp else -1

    async def get(self, k):
        if self.fail:
            raise ConnectionError("down")
        self._alive(k)
        return self.data.get(k)

    async def delete(self, k):
        return 1 if self.data.pop(k, None) is not None else 0


def test_sliding_memory():
    c = Clock()
    lim = WindowLimiter(limit=2, window_seconds=10, clock=c)
    assert lim.hit_sync("a").allowed and lim.hit_sync("a").remaining == 0
    d = lim.hit_sync("a")
    assert not d.allowed and d.retry_after == pytest.approx(10)
    assert lim.hit_sync("b").allowed
    c.t += 10.5
    assert lim.hit_sync("a").allowed


def test_invalid_config():
    with pytest.raises(ValueError):
        WindowLimiter(limit=0, window_seconds=1)
    with pytest.raises(ValueError):
        WindowLimiter(limit=1, window_seconds=0)
    with pytest.raises(ValueError):
        WindowLimiter(window_seconds=1).hit_sync("x")  # no limit anywhere
    assert WindowLimiter(window_seconds=1).hit_sync("x", limit=0) == Decision(False, 0, 0, 1.0)


def test_calendar_window_resets_at_boundary_and_per_call_limit():
    c = Clock(86400 * 5 + 86000)
    lim = WindowLimiter(window_seconds=86400, mode="calendar", clock=c)
    assert lim.hit_sync("u", 1).allowed
    d = lim.hit_sync("u", 1)
    assert not d.allowed and d.retry_after == pytest.approx(400)
    c.t += 401
    assert lim.hit_sync("u", 1).allowed


def test_full_table_closed_vs_evict():
    c = Clock()
    closed = WindowLimiter(limit=5, window_seconds=60, mode="fixed", clock=c, max_keys=3, on_full="closed")
    assert all(closed.hit_sync(f"k{i}").allowed for i in range(3))
    assert not closed.hit_sync("new").allowed and closed.hit_sync("k0").allowed
    c.t += 61
    assert closed.hit_sync("new").allowed  # stale keys swept
    ev = WindowLimiter(limit=5, window_seconds=60, clock=c, max_keys=2)
    for i in range(10):
        assert ev.hit_sync(f"k{i}").allowed
    assert len(ev.memory) <= 2


def test_count_reset():
    lim = WindowLimiter(limit=5, window_seconds=60, mode="fixed", clock=Clock())
    lim.hit_sync("a"), lim.hit_sync("a")
    assert lim.count_sync("a") == 2 and lim.reset_sync("a") == 1 and lim.count_sync("a") == 0


async def test_redis_shared_between_instances_and_expiry():
    c = Clock()
    r = FakeRedis(c)
    a = WindowLimiter(limit=2, window_seconds=60, mode="fixed", clock=c, redis=r)
    b = WindowLimiter(limit=2, window_seconds=60, mode="fixed", clock=c, redis=r)
    assert (await a.hit("k")).allowed and (await b.hit("k")).allowed
    d = await a.hit("k")
    assert not d.allowed and 1 <= d.retry_after <= 60
    assert await b.count("k") == 3
    c.t += 61
    assert (await b.hit("k")).allowed


async def test_redis_calendar_and_reset():
    c = Clock(86400 * 3 + 100)
    r = FakeRedis(c)
    lim = WindowLimiter(window_seconds=86400, mode="calendar", clock=c, redis=r)
    assert (await lim.hit("u:1", 1)).allowed
    d = await lim.hit("u:1", 1)
    assert not d.allowed and d.retry_after == pytest.approx(86300)
    assert await lim.reset("u:1") == 1 and await lim.count("u:1") == 0
    assert (await lim.hit("u:1", 1)).allowed


async def test_redis_failure_policies():
    c = Clock()
    mem = WindowLimiter(limit=1, window_seconds=60, clock=c, redis=FakeRedis(c, fail=True))
    assert (await mem.hit("k")).allowed and not (await mem.hit("k")).allowed  # per-process fallback
    opn = WindowLimiter(limit=1, window_seconds=60, clock=c, redis=FakeRedis(c, True), on_error="open")
    assert (await opn.hit("k")).allowed and (await opn.hit("k")).allowed
    clo = WindowLimiter(limit=1, window_seconds=60, clock=c, redis=FakeRedis(c, True), on_error="closed")
    assert not (await clo.hit("k")).allowed


async def test_async_without_redis_is_memory():
    lim = WindowLimiter(limit=1, window_seconds=60, clock=Clock())
    assert (await lim.hit("k")).allowed and not (await lim.hit("k")).allowed


def test_make_redis_client_none_without_url():
    assert make_redis_client(None) is None and make_redis_client("") is None


def test_service_copies_are_identical():
    """Services carry a byte-identical copy (they cannot depend on this package at build time)."""
    root = Path(__file__).resolve().parents[3]
    canon = (root / "packages/py-common/src/ff_common/ratelimit.py").read_bytes()
    for svc in ("messaging", "assistant"):
        copy = next((root / f"services/{svc}/src").glob("ff_*/ratelimit.py"))
        assert copy.read_bytes() == canon, f"{copy} drifted from ff_common/ratelimit.py"
