import asyncio
import contextlib
import time

from ff_logistics.adapters.fx import FxService, MockFx
from ff_logistics.clients.geo import CachedGeo, MockGeo
from ff_logistics.domain.engine import Engine
from ff_logistics.schemas import LandedCostRequest
from ff_logistics.testing import req


class CountingGeo(MockGeo):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def resolve_city(self, *a):
        self.calls += 1
        return await super().resolve_city(*a)

    async def hubs(self, *a, **k):
        self.calls += 1
        return await super().hubs(*a, **k)

    async def nearest_hubs(self, *a, **k):
        self.calls += 1
        return await super().nearest_hubs(*a, **k)

    async def distance_km(self, *a, **k):
        self.calls += 1
        return await super().distance_km(*a, **k)


def _quote(geo, **kw):
    q = asyncio.run(Engine(geo, FxService(MockFx())).quote(LandedCostRequest(**req(**kw))))
    return {k: v for k, v in q.items() if k not in ("id", "created_at")}


def test_cached_geo_gives_identical_quotes_with_fewer_inner_calls():
    raw, inner = CountingGeo(), CountingGeo()
    cached = CachedGeo(inner)
    expected = _quote(raw)
    assert _quote(cached) == expected
    first = inner.calls
    assert first < raw.calls  # repeated lookups inside one quote are deduped
    assert _quote(cached) == expected
    assert inner.calls == first  # second identical quote: zero upstream geo calls


def test_cached_geo_ttl_expiry_and_errors_not_cached():
    t = [0.0]
    inner = CountingGeo()
    g = CachedGeo(inner, ttl_s=10, clock=lambda: t[0])
    asyncio.run(g.resolve_city("CN", "Shanghai"))
    asyncio.run(g.resolve_city("CN", "Shanghai"))
    assert inner.calls == 1
    t[0] = 11
    asyncio.run(g.resolve_city("CN", "Shanghai"))
    assert inner.calls == 2

    class Boom(MockGeo):
        n = 0

        async def hubs(self, *a, **k):
            Boom.n += 1
            raise RuntimeError("down")

    b = CachedGeo(Boom())
    for _ in range(2):
        with contextlib.suppress(RuntimeError):
            asyncio.run(b.hubs("CN"))
    assert Boom.n == 2


def test_cached_geo_bounded():
    g = CachedGeo(MockGeo(), max_entries=3)
    for c in ("shanghai", "yiwu", "ningbo", "shenzhen", "guangzhou"):
        asyncio.run(g.resolve_city("CN", c))
    assert len(g._data) <= 3


def test_in_process_quote_is_fast():
    geo = CachedGeo(MockGeo())
    _quote(geo)
    t = time.perf_counter()
    for _ in range(20):
        _quote(geo)
    assert (time.perf_counter() - t) / 20 < 0.06
