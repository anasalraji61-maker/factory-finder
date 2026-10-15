import httpx
import pytest

from ff_sourcing.adapters.mock import MockAdapter
from ff_sourcing.adapters.registry import AdapterRegistry
from ff_sourcing.clients.trust import MockTrustClient, TrustInfo
from ff_sourcing.config import Settings
from ff_sourcing.main import create_app

A = {"X-Supplier-Id": "sup_native_a"}
B = {"X-Supplier-Id": "sup_native_b"}
GREEN = TrustInfo(supplier_id="x", score=90, band="green")
BODY = {
    "kind": "product", "condition": "new", "title": "Zebrafish ceramic planter", "description": "Hand glazed.",
    "category": "furniture", "unit": "piece", "moq": 100, "incoterm": "FOB",
    "price": {"min": {"amount": "2.50", "currency": "USD"}, "max": {"amount": "4.10", "currency": "USD"}},
    "origin": {"country_code": "IQ", "city": "Baghdad"}, "images": ["https://cdn.example.com/a.jpg"],
}


def make_app(**settings):
    trust = MockTrustClient({"sup_native_a": GREEN, "sup_native_b": GREEN})
    return create_app(Settings(database_url="sqlite+aiosqlite:///:memory:", **settings), AdapterRegistry([MockAdapter()]), trust)


async def create(c, headers):
    r = await c.post("/v1/my/listings", json=BODY, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()

TOK = {"X-Internal-Token": "s3cret"}


@pytest.fixture
async def pc():
    app = make_app(internal_token="s3cret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers=TOK) as c:
        yield c


async def test_internal_routes_404_for_non_internal(pc):
    assert (await pc.post("/v1/internal/users/u1/export", headers={"X-Internal-Token": "x"})).status_code == 404
    assert (await pc.delete("/v1/internal/users/u1/data", headers={"X-Internal-Token": ""})).status_code == 404


async def test_erase_deletes_only_the_users_supplier_listings_idempotently(pc):
    la = await create(pc, {**A, **TOK})
    lb = await create(pc, {**B, **TOK})
    exp = (await pc.post("/v1/internal/users/u1/export", headers=A)).json()
    assert [x["id"] for x in exp["data"]["listings"]] == [la["id"]]
    assert (await pc.post("/v1/internal/users/u1/export")).json()["data"]["listings"] == []  # no verified supplier passed
    assert (await pc.delete("/v1/internal/users/u1/data", headers=A)).json()["counts"]["listings_deleted"] == 1
    assert (await pc.delete("/v1/internal/users/u1/data", headers=A)).json()["counts"]["listings_deleted"] == 0
    assert (await pc.get("/v1/my/listings", headers=A)).json()["total"] == 0
    assert (await pc.get("/v1/my/listings", headers=B)).json()["total"] == 1 and lb["id"]
