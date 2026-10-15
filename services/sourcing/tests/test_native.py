"""Supplier-owned (native) listings: CRUD, ownership, validation, visibility, gating, limits."""

import copy

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
RED = TrustInfo(supplier_id="x", score=20, band="red")
UNKNOWN = TrustInfo(supplier_id="x")

BODY = {
    "kind": "product",
    "condition": "new",
    "title": "Zebrafish ceramic planter",
    "title_ar": "أصيص خزفي",
    "description": "Hand glazed.\nSet of 4.",
    "category": "furniture",
    "price": {"min": {"amount": "2.50", "currency": "USD"}, "max": {"amount": "4.10", "currency": "USD"}},
    "unit": "piece",
    "moq": 100,
    "incoterm": "FOB",
    "unit_weight_kg": 1.2,
    "unit_volume_m3": 0.01,
    "hs_code": "691390",
    "lead_time_days": {"min": 10, "max": 20},
    "images": ["https://cdn.example.com/a.jpg"],
    "origin": {"country_code": "IQ", "city": "Baghdad"},
}


def make_app(trust=None, **settings):
    trust = trust or MockTrustClient(
        {"sup_native_a": GREEN, "sup_native_b": GREEN}
    )
    return create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:", **settings),
        AdapterRegistry([MockAdapter()]),
        trust,
    )


@pytest.fixture
async def nc():
    app = make_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.app = app
        yield c


def body(**over):
    b = copy.deepcopy(BODY)
    b.update(over)
    return b


async def create(c, headers=A, **over):
    r = await c.post("/v1/my/listings", json=body(**over), headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_requires_verified_supplier_header(nc):
    for h in ({}, {"X-Supplier-Id": ""}, {"X-Supplier-Id": "not_a_supplier"}):
        for method, path in (("GET", "/v1/my/listings"), ("POST", "/v1/my/listings")):
            r = await nc.request(method, path, headers=h, json=BODY if method == "POST" else None)
            assert r.status_code == 403 and r.json()["error"]["code"] == "supplier_required"


async def test_internal_token_enforced_when_configured(monkeypatch):
    app = make_app(internal_token="sekret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/v1/my/listings", headers=A)
        assert r.status_code == 401
        r = await c.get("/v1/my/listings", headers={**A, "X-Internal-Token": "wrong"})
        assert r.status_code == 401
        r = await c.get("/v1/my/listings", headers={**A, "X-Internal-Token": "sekret"})
        assert r.status_code == 200
        assert (await c.get("/v1/categories")).status_code == 200  # public routes unaffected


async def test_create_defaults_draft_and_derives_supplier(nc):
    spoof = {
        "supplier": {"id": "sup_cn_001", "name": "Evil"},
        "supplier_id": "sup_cn_001",
        "source": "mock",
        "status": "published",
        "id": "lst_0001",
    }
    d = await create(nc, **spoof)
    assert d["id"].startswith("nat_") and len(d["id"]) == 12
    assert d["status"] == "draft" and d["source"] == "native"
    assert d["supplier"]["id"] == "sup_native_a"
    assert d["price"]["min"] == {"amount": "2.50", "currency": "USD"}
    assert d["origin"]["country_code"] == "IQ" and d["lead_time_days"] == {"min": 10, "max": 20}
    assert d["created_at"] and "published_at" not in d


async def test_crud_roundtrip(nc):
    d = await create(nc)
    lid = d["id"]
    got = (await nc.get(f"/v1/my/listings/{lid}", headers=A)).json()
    assert got["title"] == BODY["title"] and got["description"] == "Hand glazed.\nSet of 4."
    r = await nc.put(f"/v1/my/listings/{lid}", json=body(title="New title", moq=5), headers=A)
    assert r.status_code == 200 and r.json()["title"] == "New title" and r.json()["moq"] == 5
    assert r.json()["status"] == "draft" and r.json()["created_at"] == d["created_at"]
    page = (await nc.get("/v1/my/listings", headers=A)).json()
    assert page["total"] == 1 and page["items"][0]["id"] == lid and page["page"] == 1
    assert (await nc.get("/v1/my/listings", params={"status": "published"}, headers=A)).json()["total"] == 0
    assert (await nc.get("/v1/my/listings", params={"status": "bogus"}, headers=A)).status_code == 422
    assert (await nc.delete(f"/v1/my/listings/{lid}", headers=A)).status_code == 204
    assert (await nc.get(f"/v1/my/listings/{lid}", headers=A)).status_code == 404
    assert (await nc.delete(f"/v1/my/listings/{lid}", headers=A)).status_code == 404


async def test_ownership_idor_returns_404(nc):
    lid = (await create(nc))["id"]
    for method, path, kw in (
        ("GET", f"/v1/my/listings/{lid}", {}),
        ("PUT", f"/v1/my/listings/{lid}", {"json": body()}),
        ("DELETE", f"/v1/my/listings/{lid}", {}),
        ("POST", f"/v1/my/listings/{lid}/publish", {}),
        ("POST", f"/v1/my/listings/{lid}/unpublish", {}),
    ):
        r = await nc.request(method, path, headers=B, **kw)
        assert r.status_code == 404 and r.json()["error"]["code"] == "listing_not_found", (method, path)
    assert (await nc.get("/v1/my/listings", headers=B)).json()["total"] == 0
    # still intact for the owner, and not published by B's attempt
    assert (await nc.get(f"/v1/my/listings/{lid}", headers=A)).json()["status"] == "draft"


@pytest.mark.parametrize(
    "over",
    [
        {"title": "ab"},
        {"title": "x" * 141},
        {"title": "   \x00\x07  "},
        {"title_ar": "x"},
        {"description": "d" * 4001},
        {"kind": "bogus"},
        {"condition": "broken"},
        {"category": "nope"},
        {"category": "metals"},  # leaf of another kind
        {"category": "product"},  # not a leaf
        {"price": {"min": {"amount": "5", "currency": "USD"}, "max": {"amount": "4", "currency": "USD"}}},
        {"price": {"min": {"amount": "0", "currency": "USD"}, "max": {"amount": "4", "currency": "USD"}}},
        {"price": {"min": {"amount": "-1", "currency": "USD"}, "max": {"amount": "4", "currency": "USD"}}},
        {"price": {"min": {"amount": "1e3", "currency": "USD"}, "max": {"amount": "4", "currency": "USD"}}},
        {"price": {"min": {"amount": "NaN", "currency": "USD"}, "max": {"amount": "4", "currency": "USD"}}},
        {"price": {"min": {"amount": "1", "currency": "usd"}, "max": {"amount": "4", "currency": "usd"}}},
        {"price": {"min": {"amount": "1", "currency": "USD"}, "max": {"amount": "4", "currency": "EUR"}}},
        {"price": {"min": {"amount": "1.1234567", "currency": "USD"}, "max": {"amount": "4", "currency": "USD"}}},
        {"moq": 0},
        {"unit": ""},
        {"unit_weight_kg": 0},
        {"unit_weight_kg": 2_000_000},
        {"unit_volume_m3": -1},
        {"hs_code": "12345"},
        {"hs_code": "12345678901"},
        {"hs_code": "6913.90"},
        {"incoterm": "XYZ"},
        {"lead_time_days": {"min": 30, "max": 10}},
        {"lead_time_days": {"min": 0, "max": 5000}},
        {"images": [f"https://x.example/{i}.jpg" for i in range(9)]},
        {"images": ["ftp://x.example/a.jpg"]},
        {"images": ["javascript:alert(1)"]},
        {"images": ["data:image/png;base64,AAAA"]},
        {"images": ["https://x.example/a b.jpg"]},
        {"origin": {"country_code": "iq"}},
        {"origin": None},
        {"origin": {"country_code": "IQ", "point": {"lat": 91, "lon": 0}}},
        {"specs": {f"k{i}": "v" for i in range(21)}},
    ],
)
async def test_validation_rejects(nc, over):
    r = await nc.post("/v1/my/listings", json=body(**over), headers=A)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", over
    r = await nc.post("/v1/my/listings", json=body(**over), headers=A)  # nothing was stored
    assert (await nc.get("/v1/my/listings", headers=A)).json()["total"] == 0


async def test_validation_accepts_bounds(nc):
    d = await create(
        nc,
        title="a" * 140,
        description="d" * 4000,
        moq=1,
        hs_code="6913901234",
        images=[f"http://x.example/{i}.jpg" for i in range(8)],
        price={"min": {"amount": "0.000001", "currency": "EUR"}, "max": {"amount": "0.000001", "currency": "EUR"}},
        origin={"country_code": "CN", "point": {"lat": 23.1, "lon": 113.2}},
        lead_time_days=None,
        incoterm=None,
    )
    assert d["hs_code"] == "6913901234" and len(d["images"]) == 8 and "lead_time_days" not in d


async def test_sanitizes_control_and_bidi_chars(nc):
    d = await create(
        nc,
        title="Pla\x00nter‮  big\x07  size",
        description="line1\x00\r\n‫line2\x1b",
        specs={"Col\x00or": "Bl\x07ue"},
    )
    assert d["title"] == "Planter big size"
    assert "\x00" not in d["description"] and "‫" not in d["description"] and "\x1b" not in d["description"]
    assert d["specs"] == {"Color": "Blue"}


async def test_search_visibility_and_lifecycle(nc):
    lid = (await create(nc))["id"]

    async def found():
        r = (await nc.get("/v1/search", params={"q": "zebrafish planter"})).json()
        return [i for i in r["items"] if i["id"] == lid], r

    assert (await found())[0] == []  # draft is invisible
    assert (await nc.get(f"/v1/listings/{lid}")).status_code == 404
    r = await nc.post(f"/v1/my/listings/{lid}/publish", headers=A)
    assert r.status_code == 200 and r.json()["status"] == "published" and r.json()["published_at"]
    hits, resp = await found()
    assert len(hits) == 1 and hits[0]["source"] == "native" and hits[0]["supplier"]["id"] == "sup_native_a"
    assert hits[0]["supplier"]["trust_band"] == "green"
    assert {
        k: v for k, v in next(s for s in resp["sources"] if s["source"] == "native").items() if k != "warning"
    } == {"source": "native", "status": "ok", "count": 1}
    detail = (await nc.get(f"/v1/listings/{lid}")).json()
    assert detail["description"].startswith("Hand glazed") and detail["supplier"]["trust_band"] == "green"
    # filters apply like for any other source
    q = {"q": "zebrafish", "origin_country": "IQ", "category": "furniture", "kind": "product"}
    assert any(i["id"] == lid for i in (await nc.get("/v1/search", params=q)).json()["items"])
    q["origin_country"] = "CN"
    assert not any(i["id"] == lid for i in (await nc.get("/v1/search", params=q)).json()["items"])
    # edits show up immediately (no stale cache)
    await nc.put(f"/v1/my/listings/{lid}", json=body(title="Zebrafish renamed vase"), headers=A)
    assert (await nc.get(f"/v1/listings/{lid}")).json()["title"] == "Zebrafish renamed vase"
    # unpublish archives and hides again
    r = await nc.post(f"/v1/my/listings/{lid}/unpublish", headers=A)
    assert r.json()["status"] == "archived"
    assert (await found())[0] == [] and (await nc.get(f"/v1/listings/{lid}")).status_code == 404
    assert (await nc.post(f"/v1/my/listings/{lid}/unpublish", headers=A)).status_code == 409
    assert (await nc.get(f"/v1/my/listings/{lid}", headers=A)).json()["status"] == "archived"
    assert (await nc.post(f"/v1/my/listings/{lid}/publish", headers=A)).json()["status"] == "published"


async def test_same_title_listings_not_merged_in_search(nc):
    ids = [(await create(nc, title="Twin planter"))["id"] for _ in range(2)]
    for i in ids:
        await nc.post(f"/v1/my/listings/{i}/publish", headers=A)
    got = {i["id"] for i in (await nc.get("/v1/search", params={"q": "twin planter"})).json()["items"]}
    assert set(ids) <= got


async def test_supplier_endpoint_for_native_supplier(nc):
    lid = (await create(nc))["id"]
    assert (await nc.get("/v1/suppliers/sup_native_a")).status_code == 404  # nothing public yet
    await nc.post(f"/v1/my/listings/{lid}/publish", headers=A)
    s = (await nc.get("/v1/suppliers/sup_native_a")).json()
    assert s["listing_count"] == 1 and s["source"] == "native" and s["trust_band"] == "green"


async def test_native_source_listed(nc):
    srcs = {s["id"]: s for s in (await nc.get("/v1/sources")).json()}
    assert srcs["native"]["enabled"] and srcs["native"]["status"] == "ok"


@pytest.mark.parametrize(
    ("info", "status", "code"),
    [(RED, 403, "trust_blocked"), (UNKNOWN, 503, "trust_unavailable")],
)
async def test_publish_gating(info, status, code):
    app = make_app(MockTrustClient({"sup_native_a": info}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        lid = (await create(c))["id"]  # drafting is never gated
        r = await c.post(f"/v1/my/listings/{lid}/publish", headers=A)
        assert r.status_code == status and r.json()["error"]["code"] == code
        assert (await c.get(f"/v1/my/listings/{lid}", headers=A)).json()["status"] == "draft"
        assert (await c.get(f"/v1/listings/{lid}")).status_code == 404


async def test_publish_fails_closed_when_trust_raises():
    class Boom:
        async def get(self, supplier_id):
            raise RuntimeError("down")

    app = make_app(Boom())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        lid = (await create(c))["id"]
        r = await c.post(f"/v1/my/listings/{lid}/publish", headers=A)
        assert r.status_code == 503
        assert (await c.get("/v1/my/listings", headers=A)).status_code == 200  # other ops unaffected


async def test_cap_per_supplier():
    app = make_app(max_listings_per_supplier=3, create_rate_per_hour=1000)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        ids = [(await create(c))["id"] for _ in range(3)]
        r = await c.post("/v1/my/listings", json=BODY, headers=A)
        assert r.status_code == 409 and r.json()["error"]["code"] == "listing_cap_reached"
        assert (await create(c, headers=B))["id"]  # per supplier
        await c.delete(f"/v1/my/listings/{ids[0]}", headers=A)
        assert (await create(c))["id"]


async def test_create_rate_limit():
    app = make_app(create_rate_per_hour=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        lid = (await create(c))["id"]
        await create(c)
        r = await c.post("/v1/my/listings", json=BODY, headers=A)
        assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
        assert int(r.headers["retry-after"]) > 0
        await c.delete(f"/v1/my/listings/{lid}", headers=A)  # deleting does not reset the window
        assert (await c.post("/v1/my/listings", json=BODY, headers=A)).status_code == 429
        assert (await create(c, headers=B))["id"]  # other suppliers unaffected
        assert (await c.put(f"/v1/my/listings/{lid}", json=BODY, headers=A)).status_code == 404


# ---- bulk import ---------------------------------------------------------
IMP = "/v1/my/listings/import"


def item(ref, **over):
    return body(external_ref=ref, **over)


async def imp(c, items, headers=A, dry_run=None):
    payload = {"items": items}
    if dry_run is not None:
        payload["dry_run"] = dry_run
    return await c.post(IMP, json=payload, headers=headers)


async def test_import_authz(nc):
    for h in ({}, {"X-Supplier-Id": "bogus"}):
        r = await imp(nc, [item("r1")], headers=h)
        assert r.status_code == 403 and r.json()["error"]["code"] == "supplier_required"
    app = make_app(internal_token="sekret")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await imp(c, [item("r1")])).status_code == 401


async def test_import_create_then_update_idempotent(nc):
    r = await imp(nc, [item("r1"), item("r2", title="Second product")])
    d = r.json()
    assert r.status_code == 200 and (d["created"], d["updated"], d["rejected"]) == (2, 0, 0)
    ids = [x["id"] for x in d["results"]]
    assert all(i.startswith("nat_") for i in ids) and d["results"][0]["status"] == "draft"
    d2 = (await imp(nc, [item("r1", title="Renamed one"), item("r2", title="Second product")])).json()
    assert (d2["created"], d2["updated"]) == (0, 2) and [x["id"] for x in d2["results"]] == ids
    page = (await nc.get("/v1/my/listings", headers=A)).json()
    assert page["total"] == 2
    got = (await nc.get(f"/v1/my/listings/{ids[0]}", headers=A)).json()
    assert got["title"] == "Renamed one" and got["external_ref"] == "r1"


async def test_import_same_ref_is_per_supplier(nc):
    a = (await imp(nc, [item("shared")])).json()["results"][0]["id"]
    b = (await imp(nc, [item("shared")], headers=B)).json()
    assert b["created"] == 1 and b["results"][0]["id"] != a
    assert (await nc.get(f"/v1/my/listings/{a}", headers=B)).status_code == 404
    assert (await nc.get("/v1/my/listings", headers=B)).json()["total"] == 1


async def test_import_bad_items_and_in_batch_duplicates(nc):
    items = [
        item("ok1"),
        "nope",
        item("bad", category="no-such"),
        body(),  # missing external_ref
        item("ok1", title="dup in same call"),
        item("ok2", price={"min": {"amount": "5", "currency": "USD"}, "max": {"amount": "1", "currency": "USD"}}),
    ]
    d = (await imp(nc, items)).json()
    assert (d["created"], d["rejected"]) == (1, 5)
    reasons = [x.get("reason") for x in d["results"]]
    assert reasons == [None, "invalid_item", "validation_error", "validation_error", "duplicate_in_batch", "validation_error"]
    assert d["results"][2]["external_ref"] == "bad" and "id" not in d["results"][2]
    assert (await nc.get("/v1/my/listings", headers=A)).json()["total"] == 1


async def test_import_size_limits(nc):
    assert (await imp(nc, [])).status_code == 422
    assert (await imp(nc, [item(f"r{i}") for i in range(101)])).status_code == 422
    assert (await nc.post(IMP, json=[item("r1")], headers=A)).status_code == 422  # bare array is not the contract
    assert (await imp(nc, [item(f"r{i}") for i in range(100)])).json()["created"] == 100


async def test_import_dry_run_writes_nothing(nc):
    await imp(nc, [item("exists")])
    d = (await imp(nc, [item("exists", title="Changed title"), item("new"), item("bad", category="x")], dry_run=True)).json()
    assert d["dry_run"] is True and (d["created"], d["updated"], d["rejected"]) == (1, 1, 1)
    assert "id" not in d["results"][1] and "status" not in d["results"][1]
    page = (await nc.get("/v1/my/listings", headers=A)).json()
    assert page["total"] == 1 and page["items"][0]["title"] == BODY["title"]


async def test_import_respects_supplier_cap():
    app = make_app()
    app.state.native.max_per_supplier = 3
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        await create(c)
        d = (await imp(c, [item("a"), item("b"), item("c"), item("d")])).json()
        assert (d["created"], d["rejected"]) == (2, 2)
        assert [x.get("reason") for x in d["results"]] == [None, None, "listing_cap_reached", "listing_cap_reached"]
        d = (await imp(c, [item("a", title="Updated at cap"), item("e")])).json()  # updates still allowed at the cap
        assert (d["updated"], d["rejected"]) == (1, 1)
        assert (await c.get("/v1/my/listings", headers=A)).json()["total"] == 3
        dr = (await imp(c, [item("zz")], dry_run=True)).json()
        assert dr["rejected"] == 1 and dr["results"][0]["reason"] == "listing_cap_reached"


async def test_import_applies_moderation():
    app = make_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        d = (await imp(c, [item("clean"), item("dirty", description="Call me at +964 770 123 4567 or mail a@b.com")])).json()
        assert d["results"][0]["status"] == "draft" and "moderation" not in d["results"][0]
        assert d["results"][1]["status"] == "pending_review" and d["results"][1]["moderation"].startswith("Automatic screening")
        d = (await imp(c, [item("dirty")])).json()  # owner fixes content: auto flag lifts
        assert d["results"][0]["action"] == "updated" and d["results"][0]["status"] == "draft"


async def test_import_rate_limited_and_dry_run_free():
    app = make_app()
    app.state.native.imports_per_hour = 2
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        for _ in range(5):
            assert (await imp(c, [item("a")], dry_run=True)).status_code == 200
        assert (await imp(c, [item("a")])).status_code == 200
        assert (await imp(c, [item("a")])).status_code == 200
        r = await imp(c, [item("a")])
        assert r.status_code == 429 and r.headers["Retry-After"]
        assert (await imp(c, [item("a")], headers=B)).status_code == 200


async def test_import_ignores_spoofed_fields(nc):
    d = (await imp(nc, [item("s1", supplier_id="sup_cn_001", status="published", id="lst_0001")])).json()
    assert d["results"][0]["status"] == "draft"
    got = (await nc.get(f"/v1/my/listings/{d['results'][0]['id']}", headers=A)).json()
    assert got["supplier"]["id"] == "sup_native_a"
