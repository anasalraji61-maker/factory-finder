import asyncio

from ff_sourcing.adapters.base import Health, SourceAdapter
from ff_sourcing.adapters.mock import MockAdapter
from ff_sourcing.adapters.registry import AdapterRegistry
from ff_sourcing.clients.trust import MockTrustClient
from ff_sourcing.domain.models import SearchQuery
from ff_sourcing.service import SourcingService


class Slow(SourceAdapter):
    id, name = "slow", "slow"

    async def search(self, query):
        await asyncio.sleep(5)

    async def get_listing(self, i):
        return None

    async def get_supplier(self, i):
        return None

    async def health(self):
        return Health(ok=True)


class Broken(Slow):
    id = "broken"

    async def search(self, query):
        raise RuntimeError("boom")


class Twin(MockAdapter):
    """Same catalog under another source id with cheaper prices => duplicates."""

    id = "twin"

    def __init__(self):
        super().__init__()
        for item in self._listings:
            item.source = "twin"
            item.price.min.amount = item.price.min.amount / 2


def make(adapters, timeout=0.2):
    return SourcingService(AdapterRegistry(adapters), MockTrustClient(), adapter_timeout_s=timeout)


async def test_timeout_and_error_are_isolated():
    res = await make([MockAdapter(), Slow(), Broken()]).search(SearchQuery(q="pump"))
    st = {s.source: s for s in res.sources}
    assert st["mock"].status == "ok" and st["mock"].count == res.total > 0
    assert st["slow"].status == "timeout" and st["broken"].status == "error"
    assert st["slow"].count == st["broken"].count == 0


async def test_dedupe_across_sources_keeps_cheaper():
    res = await make([MockAdapter(), Twin()]).search(SearchQuery(), 1, 100)
    assert res.total == 60 and {i.source for i in res.items} == {"twin"}
    assert sum(s.count for s in res.sources) == 120


async def test_disabled_adapter_not_called():
    reg = AdapterRegistry([MockAdapter(), Broken()], enabled={"mock"})
    res = await SourcingService(reg, MockTrustClient()).search(SearchQuery())
    assert [s.source for s in res.sources] == ["mock"]
    reg.enable("broken")
    assert {a.id for a in reg.enabled()} == {"mock", "broken"}
    reg.disable("broken")
    assert not reg.is_enabled("broken")


async def test_result_cache_hits_adapter_once():
    calls = []

    class Counting(MockAdapter):
        async def search(self, query):
            calls.append(1)
            return await super().search(query)

    s = make([Counting()])
    await s.search(SearchQuery(q="pump"), 1, 5)
    await s.search(SearchQuery(q="pump"), 2, 5)
    assert len(calls) == 1
