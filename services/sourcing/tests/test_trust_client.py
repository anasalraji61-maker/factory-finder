import httpx
import respx

from ff_sourcing.adapters.mock import MockAdapter
from ff_sourcing.adapters.registry import AdapterRegistry
from ff_sourcing.clients.trust import HttpTrustClient, MockTrustClient, TrustInfo
from ff_sourcing.domain.models import SearchQuery
from ff_sourcing.service import SourcingService

BASE = "http://trust.test"


@respx.mock
async def test_http_ok():
    respx.get(f"{BASE}/v1/trust/suppliers/sup_cn_001").mock(
        return_value=httpx.Response(
            200, json={"supplier_id": "sup_cn_001", "score": 82, "band": "green"}
        )
    )
    info = await HttpTrustClient(BASE).get("sup_cn_001")
    assert (info.score, info.band) == (82, "green")


@respx.mock
async def test_http_failures_become_unknown():
    respx.get(f"{BASE}/v1/trust/suppliers/a").mock(return_value=httpx.Response(500))
    respx.get(f"{BASE}/v1/trust/suppliers/b").mock(side_effect=httpx.ConnectTimeout("t"))
    respx.get(f"{BASE}/v1/trust/suppliers/c").mock(
        return_value=httpx.Response(200, text="not json")
    )
    c = HttpTrustClient(BASE)
    for sid in "abc":
        assert (await c.get(sid)).band == "unknown"


async def test_mock_deterministic():
    a, b = await MockTrustClient().get("sup_cn_001"), await MockTrustClient().get("sup_cn_001")
    assert a == b and a.band in ("green", "yellow", "red")


async def test_search_survives_trust_outage():
    class Down:
        async def get(self, sid):
            raise RuntimeError("down")

    res = await SourcingService(AdapterRegistry([MockAdapter()]), Down()).search(
        SearchQuery(q="pump")
    )
    assert res.total > 0 and {i.supplier.trust_band for i in res.items} == {"unknown"}
    assert TrustInfo(supplier_id="x").band == "unknown"
