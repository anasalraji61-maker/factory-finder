"""Search hot path: normalisation equivalence, batched trust enrichment, pooled trust client."""
import random
import unicodedata

import httpx
import respx

from ff_sourcing.adapters.mock import MockAdapter
from ff_sourcing.adapters.registry import AdapterRegistry
from ff_sourcing.clients.trust import HttpTrustClient, MockTrustClient
from ff_sourcing.domain import text as T
from ff_sourcing.domain.models import SearchQuery
from ff_sourcing.service import SourcingService

BASE = "http://trust.test"


def _reference_normalize(text: str) -> str:  # the original, slower implementation
    text = unicodedata.normalize("NFKD", text or "").lower()
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = T._DIACRITICS.sub("", text).translate(T._ARABIC_MAP)
    text = T._CJK.sub(r" \1 ", text)
    return T._NON_WORD.sub(" ", text).strip()


def test_normalize_matches_reference():
    rnd = random.Random(7)
    pool = [chr(c) for c in [*range(32, 127), *range(0x600, 0x6FF), *range(0x300, 0x340), *range(0x4E00, 0x4E20)]]
    pool += [chr(0x130), chr(0xE9), chr(0xFB01), chr(0x660), chr(0x6F5), chr(0x640)]
    samples = ["", "  ", "Injection Molding Machine 250KG/h", "السَّلام عليكم", "خط إنتاج", "Café Crème"]
    samples += ["".join(rnd.choice(pool) for _ in range(rnd.randint(0, 30))) for _ in range(3000)]
    for s in samples:
        assert T.normalize(s) == _reference_normalize(s), repr(s)


class CountingTrust(MockTrustClient):
    def __init__(self):
        super().__init__()
        self.single = 0
        self.many: list[list[str]] = []

    async def get(self, supplier_id):
        self.single += 1
        return await super().get(supplier_id)

    async def get_many(self, ids):
        self.many.append(list(ids))
        return {i: await MockTrustClient.get(self, i) for i in ids}


async def test_enrich_uses_one_batch_call_and_cache():
    trust = CountingTrust()
    svc = SourcingService(AdapterRegistry([MockAdapter()]), trust)
    first = await svc.search(SearchQuery(q="machine"))
    assert len(trust.many) == 1 and trust.single == 0
    again = await svc.search(SearchQuery(q="machine"))  # all cached now
    assert len(trust.many) == 1
    assert first.items == again.items
    plain = await SourcingService(AdapterRegistry([MockAdapter()]), MockTrustClient()).search(SearchQuery(q="machine"))
    assert plain.items == first.items  # same result as the per-supplier path


async def test_enrich_falls_back_when_batch_raises():
    class Broken(CountingTrust):
        async def get_many(self, ids):
            raise RuntimeError("boom")

    trust = Broken()
    res = await SourcingService(AdapterRegistry([MockAdapter()]), trust).search(SearchQuery(q="machine"))
    assert res.total > 0 and trust.single > 0 and {i.supplier.trust_band for i in res.items} != {"unknown"}


@respx.mock
async def test_http_get_many_single_request_and_unknowns():
    route = respx.get(f"{BASE}/v1/trust/suppliers:batch").mock(
        return_value=httpx.Response(200, json={"items": [{"supplier_id": "a", "score": 80, "band": "green"}]})
    )
    c = HttpTrustClient(BASE)
    out = await c.get_many(["a", "b", "a"])
    await c.aclose()
    assert route.call_count == 1
    assert route.calls[0].request.url.params["ids"] == "a,b"
    assert (out["a"].score, out["a"].band) == (80, "green") and out["b"].band == "unknown"


@respx.mock
async def test_http_get_many_falls_back_per_id_when_batch_fails():
    respx.get(f"{BASE}/v1/trust/suppliers:batch").mock(return_value=httpx.Response(500))
    respx.get(f"{BASE}/v1/trust/suppliers/a").mock(return_value=httpx.Response(200, json={"score": 70, "band": "green"}))
    respx.get(f"{BASE}/v1/trust/suppliers/b").mock(return_value=httpx.Response(404))
    c = HttpTrustClient(BASE)
    out = await c.get_many(["a", "b"])
    await c.aclose()
    assert out["a"].band == "green" and out["b"].band == "unknown"


@respx.mock
async def test_http_client_is_pooled():
    respx.get(f"{BASE}/v1/trust/suppliers/a").mock(return_value=httpx.Response(200, json={"score": 1, "band": "red"}))
    c = HttpTrustClient(BASE)
    await c.get("a")
    first = c._shared
    await c.get("a")
    assert first is not None and c._shared is first
    await c.aclose()
    assert c._shared is None
