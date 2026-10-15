"""QA2: duplicate/concurrent requests (asyncio.gather) must never double-create, double-settle or double-post."""

import asyncio
import json

import httpx
from conftest import ADMIN, BUYER, DEAL, WH_SECRET, Clock, make_settings

from ff_payments import webhooks
from ff_payments.clients.deals import MockDealClient
from ff_payments.main import create_app
from ff_payments.providers.mock import MockProvider


class Boot:
    """File-backed SQLite so every request gets its own connection (a StaticPool :memory: DB would share one
    transaction between concurrent requests and hide / fake races)."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path

    async def __aenter__(self):
        self.clock = Clock()
        url = f"sqlite+aiosqlite:///{self.tmp / 'c.db'}"
        self.app = create_app(make_settings(database_url=url), provider=MockProvider(), clock=self.clock,
                              deals=MockDealClient({"deal_1": {**DEAL, "id": "deal_1"}}))
        self.cm = self.app.router.lifespan_context(self.app)
        await self.cm.__aenter__()
        self.c = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://t")
        return self

    async def __aexit__(self, *a):
        await self.c.aclose()
        await self.cm.__aexit__(*a)

    async def event(self, body, ts_off=0, secret=WH_SECRET):
        raw = json.dumps(body).encode()
        ts = int(self.clock().timestamp()) + ts_off
        return await self.c.post("/v1/payments/webhooks/mock", content=raw,
                                 headers={"X-FF-Signature": webhooks.sign(secret, raw, ts)})

    async def ledger(self, inv_id):
        return (await self.c.get("/v1/ledger", params={"invoice_id": inv_id}, headers=ADMIN)).json()["total"]


async def test_concurrent_identical_creates_yield_one_invoice(tmp_path):
    async with Boot(tmp_path) as b:
        rs = await asyncio.gather(*[b.c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"},
                                             headers=BUYER) for _ in range(8)])
        assert all(r.status_code in (200, 201) for r in rs), [r.text for r in rs]
        assert len({r.json()["id"] for r in rs}) == 1
        listing = (await b.c.get("/v1/invoices", headers=BUYER)).json()
        assert listing["total"] == 1


async def test_duplicate_confirmed_webhooks_same_event_settle_once(tmp_path):
    async with Boot(tmp_path) as b:
        inv = (await b.c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"}, headers=BUYER)).json()
        ev = {"event_id": "e1", "type": "payment.confirmed", "invoice_id": inv["id"], "tx_ref": "t1"}
        rs = await asyncio.gather(*[b.event(ev) for _ in range(6)])
        assert all(r.status_code == 200 for r in rs), [r.text for r in rs]
        assert sorted(r.json()["status"] for r in rs).count("applied") == 1
        assert await b.ledger(inv["id"]) == 2
        assert (await b.c.get("/v1/payments/outbox", headers=ADMIN)).json()["total"] == 1


async def test_distinct_event_ids_racing_to_pay_settle_once(tmp_path):
    async with Boot(tmp_path) as b:
        inv = (await b.c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"}, headers=BUYER)).json()
        rs = await asyncio.gather(*[b.event({"event_id": f"e{i}", "type": "payment.confirmed",
                                             "invoice_id": inv["id"], "tx_ref": "t1"}) for i in range(6)])
        assert all(r.status_code == 200 for r in rs), [r.text for r in rs]
        assert await b.ledger(inv["id"]) == 2
        assert (await b.c.get("/v1/payments/outbox", headers=ADMIN)).json()["total"] == 1


async def test_pay_vs_cancel_vs_refund_race_has_one_winner_and_balanced_ledger(tmp_path):
    async with Boot(tmp_path) as b:
        inv = (await b.c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"}, headers=BUYER)).json()
        pay = b.event({"event_id": "e1", "type": "payment.confirmed", "invoice_id": inv["id"]})
        cancel = b.c.post(f"/v1/invoices/{inv['id']}/cancel", headers=BUYER)
        await asyncio.gather(pay, cancel)
        final = (await b.c.get(f"/v1/invoices/{inv['id']}", headers=BUYER)).json()["status"]
        assert final in ("paid", "failed")
        assert await b.ledger(inv["id"]) == (2 if final == "paid" else 0)
        rf = await asyncio.gather(*[b.c.post(f"/v1/invoices/{inv['id']}/refund", headers=ADMIN) for _ in range(4)])
        if final == "paid":
            assert sorted(r.status_code for r in rf).count(200) == 1
            assert await b.ledger(inv["id"]) == 4
        else:
            assert all(r.status_code >= 400 for r in rf)


async def test_same_tx_ref_via_webhook_cannot_settle_two_invoices(tmp_path):
    async with Boot(tmp_path) as b:
        a = (await b.c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"}, headers=BUYER)).json()
        d = (await b.c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "deal_payment"}, headers=BUYER)).json()
        rs = await asyncio.gather(
            b.event({"event_id": "x1", "type": "payment.confirmed", "invoice_id": a["id"], "tx_ref": "same"}),
            b.event({"event_id": "x2", "type": "payment.confirmed", "invoice_id": d["id"], "tx_ref": "same"}))
        assert [r.status_code for r in rs] == [200, 200]
        st = {i["id"]: i["status"] for i in (await b.c.get("/v1/invoices", headers=BUYER)).json()["items"]}
        assert sorted(st.values()).count("paid") == 1, st




async def test_usdt_tron_webhook_cannot_settle_and_concurrent_creates_get_distinct_suffixes(tmp_path):
    from test_usdt_tron_review import Chain, prov

    deals = {f"d{i}": {**DEAL, "id": f"d{i}", "buyer_id": f"u{i}"} for i in range(6)}
    clock = Clock()
    url = f"sqlite+aiosqlite:///{tmp_path / 'u.db'}"
    app = create_app(make_settings(database_url=url, provider="off", webhook_secret_usdt_tron=WH_SECRET),
                     provider=prov(Chain()), clock=clock, deals=MockDealClient(deals))
    async with app.router.lifespan_context(app):
        c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        rs = await asyncio.gather(*[c.post("/v1/invoices", json={"deal_id": f"d{i}", "kind": "commission"},
                                           headers={"X-User-Id": f"u{i}"}) for i in range(6)])
        assert [r.status_code for r in rs] == [201] * 6, [r.text for r in rs]
        assert len({r.json()["pay_amount"]["amount"] for r in rs}) == 6  # suffix is the only payer identity
        inv = rs[0].json()
        raw = json.dumps({"event_id": "w1", "type": "payment.confirmed", "invoice_id": inv["id"]}).encode()
        h = {"X-FF-Signature": webhooks.sign(WH_SECRET, raw, int(clock().timestamp()))}
        r = await c.post("/v1/payments/webhooks/usdt_tron", content=raw, headers=h)
        assert r.status_code == 200 and r.json()["status"] == "ignored"
        got = (await c.get(f"/v1/invoices/{inv['id']}", headers={"X-User-Id": "u0"})).json()
        assert got["status"] == "awaiting_payment"
        await c.aclose()
