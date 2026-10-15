"""503 upstream_timeout vs 404 on listing detail, and the top-level partial_results warning on search."""
import asyncio

import httpx
import pytest
from fastapi import FastAPI

from ff_sourcing.adapters.base import Health, SourceAdapter
from ff_sourcing.adapters.mock import MockAdapter
from ff_sourcing.adapters.registry import AdapterRegistry
from ff_sourcing.api.errors import ApiError, install_error_handlers
from ff_sourcing.api.routes import router
from ff_sourcing.clients.trust import MockTrustClient
from ff_sourcing.domain.models import SearchQuery
from ff_sourcing.service import SourcingService


class Flaky(SourceAdapter):
    """get_listing behaviour is switchable: 'raise' | 'slow' | 'none' | the item."""

    id, name = "flaky", "flaky"

    def __init__(self, mode="raise"):
        self.mode = mode
        self.calls = 0

    async def search(self, query):
        if self.mode == "raise":
            raise RuntimeError("boom")
        if self.mode == "slow":
            await asyncio.sleep(5)
        return []

    async def get_listing(self, i):
        self.calls += 1
        if self.mode == "raise":
            raise RuntimeError("boom")
        if self.mode == "slow":
            await asyncio.sleep(5)
        return None

    async def get_supplier(self, i):
        return None

    async def health(self):
        return Health(ok=True)


class Empty(Flaky):
    id = "empty"

    def __init__(self):
        super().__init__("none")


def make(adapters, timeout=0.1):
    return SourcingService(AdapterRegistry(adapters), MockTrustClient(), adapter_timeout_s=timeout)


async def client(service):
    app = FastAPI()
    install_error_handlers(app)
    app.state.service = service

    class _A:
        async def impressions(self, ids):
            return None

    app.state.analytics = _A()
    app.include_router(router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_all_adapters_failed_is_503():
    c = await client(make([Flaky("raise"), Flaky("slow")]))
    r = await c.get("/v1/listings/x_1")
    assert r.status_code == 503 and r.json()["error"]["code"] == "upstream_timeout"


async def test_all_not_found_is_404():
    c = await client(make([Empty(), MockAdapter()]))
    r = await c.get("/v1/listings/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "listing_not_found"


async def test_failure_plus_not_found_is_503_but_hit_wins():
    svc = make([Flaky("raise"), MockAdapter()])
    c = await client(svc)
    assert (await c.get("/v1/listings/nope")).status_code == 503  # the failed source might have it
    assert (await c.get("/v1/listings/lst_0027")).status_code == 200  # a hit is a hit


async def test_price_history_also_503():
    c = await client(make([Flaky("raise")]))
    assert (await c.get("/v1/listings/x/price-history")).status_code == 503


async def test_reco_negative_cache_only_for_definite_not_found():
    flaky = Flaky("raise")
    svc = make([flaky])
    assert await svc._detail("x") is None
    assert await svc._detail("x") is None
    assert flaky.calls == 2  # failure was not cached
    ok = make([Empty()])
    assert await ok._detail("x") is None and await ok._detail("x") is None
    assert ok.registry.enabled()[0].calls == 1  # definite not-found is cached


async def test_recovery_after_outage():
    flaky = Flaky("raise")
    svc = make([flaky])
    with pytest.raises(ApiError):
        await svc.get_listing("x")
    flaky.mode = "none"
    assert await svc.get_listing("x") is None  # now a definite 404


async def test_search_partial_warning_keeps_sources():
    res = await make([MockAdapter(), Flaky("raise")]).search(SearchQuery(q="pump"))
    assert res.warning and res.warning.startswith("partial_results:") and "flaky" in res.warning
    st = {s.source: s.status for s in res.sources}
    assert st == {"mock": "ok", "flaky": "error"}


async def test_search_no_warning_when_all_ok_and_not_serialised():
    svc = make([MockAdapter()])
    res = await svc.search(SearchQuery(q="pump"))
    assert res.warning is None
    c = await client(svc)
    assert "warning" not in (await c.get("/v1/search?q=pump")).json()
    body = (await (await client(make([MockAdapter(), Flaky("slow")]))).get("/v1/search?q=pump")).json()
    assert body["warning"].startswith("partial_results:")


async def test_search_total_outage_is_200_with_warning():
    res = await make([Flaky("raise")]).search(SearchQuery(q="pump"))
    assert res.total == 0 and res.warning
