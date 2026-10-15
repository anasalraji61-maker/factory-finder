"""Anonymous amplification guards on /v1/recommendations and /v1/listings/{id}/similar."""

import asyncio

from ff_sourcing.adapters.mock import MockAdapter
from ff_sourcing.adapters.registry import AdapterRegistry
from ff_sourcing.clients.trust import MockTrustClient
from ff_sourcing.domain.cache import LRUTTLCache
from ff_sourcing.service import SourcingService

REFS = ["lst_0027", "lst_0004", "nope"]


class Counting(MockAdapter):
    def __init__(self, delay=0.0):
        super().__init__()
        self.searches = 0
        self.gets = 0
        self.live = 0
        self.peak = 0
        self.delay = delay

    async def _track(self):
        self.live += 1
        self.peak = max(self.peak, self.live)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self.live -= 1

    async def search(self, query):
        self.searches += 1
        await self._track()
        return await super().search(query)

    async def get_listing(self, listing_id):
        self.gets += 1
        await self._track()
        return await super().get_listing(listing_id)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def svc(adapter, **kw):
    return SourcingService(AdapterRegistry([adapter]), MockTrustClient(), **kw)


async def test_pool_and_detail_cache_across_requests():
    a = Counting()
    s = svc(a, reco_response_ttl_s=0)  # response cache off: isolate pool/detail caches
    first = await s.recommendations(REFS, "IN", 10)
    n_search, n_get = a.searches, a.gets
    assert n_search >= 1 and n_get == 3  # one lookup per distinct ref
    again = await s.recommendations(["lst_0004", "lst_0027"], None, 5)  # different shape, same refs/pools
    assert a.searches == n_search and a.gets == n_get
    assert first[0] == ["lst_0027", "lst_0004"] and again[0] == ["lst_0004", "lst_0027"]


async def test_response_cache_and_order_matters():
    a = Counting()
    s = svc(a)
    r1 = await s.recommendations(["lst_0027", "lst_0004", "lst_0027"], "in", 10)
    calls = (a.searches, a.gets)
    assert await s.recommendations(["lst_0027", "lst_0004"], "IN", 10) == r1  # dedupe + country case normalised
    assert (a.searches, a.gets) == calls
    r3 = await s.recommendations(["lst_0004", "lst_0027"], "IN", 10)  # other order = other weights = own entry
    assert r3[0] == ["lst_0004", "lst_0027"]


async def test_ttl_expiry_and_disabled():
    clock = Clock()
    a = Counting()
    s = svc(a, clock=clock, reco_cache_ttl_s=60, reco_response_ttl_s=30, cache_ttl_s=0)  # inner search cache off
    await s.recommendations(REFS, None, 10)
    base = (a.searches, a.gets)
    clock.t += 29
    await s.recommendations(REFS, None, 10)
    assert (a.searches, a.gets) == base
    clock.t += 2  # response (30 s) expired, pool/detail (60 s) still fresh
    await s.recommendations(REFS, None, 10)
    assert (a.searches, a.gets) == base
    clock.t += 40  # everything expired
    await s.recommendations(REFS, None, 10)
    assert a.gets == base[1] * 2 and a.searches > base[0]

    b = Counting()
    off = svc(b, reco_cache_ttl_s=0, reco_response_ttl_s=0)
    await off.recommendations(REFS, None, 10)
    g = b.gets
    await off.recommendations(REFS, None, 10)
    assert b.gets == 2 * g


async def test_invalidate_drops_caches():
    a = Counting()
    s = svc(a)
    await s.recommendations(REFS, None, 10)
    g = a.gets
    s.invalidate_reco()
    await s.recommendations(REFS, None, 10)
    assert a.gets == 2 * g


async def test_semaphore_bounds_provider_calls():
    a = Counting(delay=0.02)
    s = svc(a, provider_concurrency=3, reco_budget_s=10)
    refs = [f"lst_{n:04d}" for n in range(1, 21)]
    await s.recommendations(refs, None, 10)
    assert a.gets == 20 and 1 <= a.peak <= 3


async def test_budget_exhaustion_returns_partial_with_warning():
    a = Counting(delay=0.5)
    s = svc(a, reco_budget_s=0.05, adapter_timeout_s=5)
    based_on, items, warning = await s.recommendations(REFS, None, 10)
    assert warning and warning.startswith("partial_results") and based_on == [] and isinstance(items, list)
    assert not len(s._reco_resp)  # partial answers are never cached
    a.delay = 0
    _, items, warning = await s.recommendations(REFS, None, 10)
    assert warning is None and items


async def test_budget_exhaustion_http_additive_field():
    import httpx

    from ff_sourcing.config import Settings
    from ff_sourcing.main import create_app

    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:", reco_budget_s=0.05),
        AdapterRegistry([Counting(delay=0.5)]),
        MockTrustClient(),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        d = (await c.get("/v1/recommendations", params={"ref": "lst_0027"})).json()
        assert d["warning"].startswith("partial_results") and d["items"] == []
        r = await c.get("/v1/listings/lst_0027/similar")
        assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_timeout"


async def test_no_warning_field_when_complete():
    import httpx

    from ff_sourcing.config import Settings
    from ff_sourcing.main import create_app

    app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"), AdapterRegistry([MockAdapter()]), MockTrustClient())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        d = (await c.get("/v1/recommendations", params={"ref": "lst_0027"})).json()
        assert "warning" not in d
        assert "warning" not in (await c.get("/v1/listings/lst_0027/similar")).json()


async def test_no_cross_request_leakage_and_isolated_mutation():
    """Cached values are keyed by public inputs only; a caller's enrichment never mutates shared entries."""
    a = Counting()
    s = svc(a)
    r1 = await s.recommendations(["lst_0027"], None, 10)
    r2 = await s.recommendations(["lst_0004"], None, 10)
    assert r1 != r2
    ref_before = (await s._detail("lst_0027")).supplier.trust_band
    await s.similar("lst_0027", 5)
    assert (await s._detail("lst_0027")).supplier.trust_band == ref_before


def test_lru_ttl_cache_cap_and_recency():
    clock = Clock()
    c = LRUTTLCache(10, 3, clock)
    for k in "abc":
        c.set(k, k)
    assert c.get("a") == "a"  # touch a: b is now the oldest
    c.set("d", "d")
    assert len(c) == 3 and c.get("b") is LRUTTLCache.MISS and c.get("a") == "a"
    c.set("n", None)
    assert c.get("n") is None  # None is a cacheable value
    clock.t += 11
    assert c.get("a") is LRUTTLCache.MISS
    z = LRUTTLCache(0, 3, clock)
    z.set("x", 1)
    assert len(z) == 0 and z.get("x") is LRUTTLCache.MISS


async def test_pool_cache_memory_cap():
    a = Counting()
    s = svc(a, reco_cache_max=2)
    for i in range(20):
        await s.recommendations([f"lst_{i + 1:04d}"], None, 5)
    assert len(s._details) <= 2 and len(s._pools) <= 2 and len(s._reco_resp) <= 2
