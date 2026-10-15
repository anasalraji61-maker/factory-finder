"""Deal lifecycle: payments callback (idempotent, both-invoices rule, refunds), user transitions, event log."""

import pytest
from conftest import BUYER, SUP_A, SUP_B, new_offer, new_request
from fastapi.testclient import TestClient
from sqlalchemy import select

from ff_rfq.config import Settings
from ff_rfq.db import DealEventImmutable, DealEventRow
from ff_rfq.main import create_app

SUP_REF = "sup_a"
SUP_A_V = {**SUP_A, "X-Supplier-Id": SUP_REF}
N = [0]


def make_deal(client, sup=SUP_A_V):
    req = new_request(client)
    off = new_offer(client, req["id"], sup, "10.00")
    return client.post(f"/v1/offers/{off['id']}/accept", headers=BUYER).json()


def cb(client, deal, kind="deal_payment", status="paid", other_open=(), event_id=None, amount=None, headers=None, inv=None):
    N[0] += 1
    m = amount or (deal["subtotal"] if kind == "deal_payment" else deal["commission"]["amount"])
    body = {"invoice_id": inv or f"inv_{kind}", "kind": kind, "status": status, "amount": m,
            "event_id": event_id or f"evt_{N[0]}", "other_open_kinds": list(other_open)}
    return client.post(f"/v1/internal/deals/{deal['id']}/payment-status", json=body, headers=headers or {})


def status(client, deal):
    return client.get(f"/v1/deals/{deal['id']}", headers=BUYER).json()["status"]


def test_single_invoice_paid_advances_and_is_idempotent(client):
    d = make_deal(client)
    r = cb(client, d, event_id="e1")
    assert r.status_code == 200 and r.json()["outcome"] == "applied" and r.json()["deal_status"] == "paid"
    again = cb(client, d, event_id="e1")  # redelivery
    assert again.json()["outcome"] == "duplicate" and status(client, d) == "paid"
    other = cb(client, d, event_id="e2")  # same fact, new event id: no second transition
    assert other.json()["outcome"] == "ignored"
    ev = client.get(f"/v1/deals/{d['id']}/events", headers=BUYER).json()["items"]
    assert [e["action"] for e in ev] == ["payment_paid", "payment_paid"]
    assert ev[0]["from_status"] == "pending_payment" and ev[0]["to_status"] == "paid"
    assert ev[0]["actor_role"] == "system"


def test_both_invoices_rule(client):
    d = make_deal(client)
    r = cb(client, d, "deal_payment", other_open=["commission"])  # commission invoice still open
    assert r.json()["outcome"] == "recorded" and status(client, d) == "pending_payment"
    assert r.json()["payment"] == {"commission": "open", "deal_payment": "paid"}
    r = cb(client, d, "commission")
    assert r.json()["deal_status"] == "paid" and r.json()["payment"] == {"commission": "paid", "deal_payment": "paid"}
    # commission first, then deal payment, works the same
    d2 = make_deal(client)
    assert cb(client, d2, "commission", other_open=["deal_payment"]).json()["deal_status"] == "pending_payment"
    assert cb(client, d2, "deal_payment").json()["deal_status"] == "paid"


def test_only_commission_invoice_is_enough_when_no_other_exists(client):
    d = make_deal(client)
    assert cb(client, d, "commission").json()["deal_status"] == "paid"


def test_require_both_invoices_setting():
    s = Settings(database_url="sqlite+aiosqlite:///:memory:", sourcing_client="mock", require_both_invoices=True)
    with TestClient(create_app(s)) as c:
        d = make_deal(c)
        assert cb(c, d, "deal_payment").json()["deal_status"] == "pending_payment"  # commission not reported yet
        assert cb(c, d, "commission").json()["deal_status"] == "paid"


def test_refund_paths(client):
    # deal_payment refunded after paid -> refunded (terminal)
    d = make_deal(client)
    cb(client, d)
    r = cb(client, d, status="refunded")
    assert r.json()["deal_status"] == "refunded"
    assert cb(client, d).json()["deal_status"] == "refunded"  # a late paid event never resurrects it
    # commission refunded after paid -> back to pending_payment, paid again once re-paid
    d = make_deal(client)
    cb(client, d, "commission")
    r = cb(client, d, "commission", "refunded")
    assert r.json()["deal_status"] == "pending_payment" and r.json()["payment"]["commission"] == "refunded"
    assert cb(client, d, "commission", inv="inv_commission_2").json()["deal_status"] == "paid"  # a NEW invoice
    # refund during fulfilment -> disputed; after completion -> only recorded
    d = make_deal(client)
    cb(client, d)
    assert client.post(f"/v1/deals/{d['id']}/fulfilment/start", headers=SUP_A_V).status_code == 200
    assert cb(client, d, status="refunded").json()["deal_status"] == "disputed"
    d = make_deal(client)
    cb(client, d)
    client.post(f"/v1/deals/{d['id']}/fulfilment/start", headers=SUP_A_V)
    client.post(f"/v1/deals/{d['id']}/confirm-receipt", headers=BUYER)
    r = cb(client, d, status="refunded")
    assert r.json()["deal_status"] == "completed" and r.json()["outcome"] == "recorded"


def test_amount_mismatch_and_unknown_deal_and_validation(client):
    d = make_deal(client)
    r = cb(client, d, amount={"amount": "1.00", "currency": "USD"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "amount_mismatch"
    r = cb(client, d, amount={"amount": d["subtotal"]["amount"], "currency": "EUR"})
    assert r.status_code == 422
    assert status(client, d) == "pending_payment"
    assert cb(client, {**d, "id": "deal_nope"}).status_code == 404
    bad = client.post(f"/v1/internal/deals/{d['id']}/payment-status", json={"kind": "x"})
    assert bad.status_code == 422


def test_internal_token_guard():
    s = Settings(database_url="sqlite+aiosqlite:///:memory:", sourcing_client="mock", internal_token="tok")
    with TestClient(create_app(s)) as c:
        good = {"X-Internal-Token": "tok"}
        req = c.post("/v1/requests", headers={**BUYER, **good}, json={"kind": "product", "title": "Lights", "quantity": "10"}).json()
        off = c.post(f"/v1/requests/{req['id']}/offers", headers={**SUP_A, **good},
                     json={"price": {"amount": "5", "currency": "USD"}, "supplier_name": "A"}).json()
        d = c.post(f"/v1/offers/{off['id']}/accept", headers={**BUYER, **good}).json()
        for h in ({}, {"X-Internal-Token": "wrong"}, BUYER):
            r = cb(c, d, headers=h)
            assert r.status_code == 401, h
        assert c.get(f"/v1/deals/{d['id']}", headers={**BUYER, **good}).json()["status"] == "pending_payment"
        assert cb(c, d, headers={**BUYER, **good}).status_code == 200


def test_fulfilment_flow_and_event_log(client):
    d = make_deal(client)
    # not paid yet
    r = client.post(f"/v1/deals/{d['id']}/fulfilment/start", headers=SUP_A_V)
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_deal_transition"
    cb(client, d)
    r = client.post(f"/v1/deals/{d['id']}/fulfilment/start", headers=SUP_A_V)
    assert r.status_code == 200 and r.json()["status"] == "in_fulfilment"
    assert client.post(f"/v1/deals/{d['id']}/fulfilment/start", headers=SUP_A_V).json()["status"] == "in_fulfilment"
    r = client.post(f"/v1/deals/{d['id']}/delivered", headers=SUP_A_V)
    assert r.status_code == 200 and r.json()["delivered_at"] and r.json()["status"] == "in_fulfilment"
    first = r.json()["delivered_at"]
    assert client.post(f"/v1/deals/{d['id']}/delivered", headers=SUP_A_V).json()["delivered_at"] == first
    r = client.post(f"/v1/deals/{d['id']}/confirm-receipt", headers=BUYER)
    assert r.status_code == 200 and r.json()["status"] == "completed" and r.json()["completed_at"]
    assert client.post(f"/v1/deals/{d['id']}/confirm-receipt", headers=BUYER).json()["status"] == "completed"
    ev = client.get(f"/v1/deals/{d['id']}/events", headers=SUP_A_V).json()
    assert [e["action"] for e in ev["items"]] == [
        "payment_paid", "fulfilment_started", "delivered", "receipt_confirmed"]
    assert [e["seq"] for e in ev["items"]] == [1, 2, 3, 4]
    assert [e["actor_role"] for e in ev["items"]] == ["system", "supplier", "supplier", "buyer"]
    assert "supplier_user_id" not in str(ev) and "supA" not in str(ev)


def test_transition_ownership_and_idor(client):
    d = make_deal(client)
    cb(client, d)
    url = f"/v1/deals/{d['id']}"
    assert client.post(f"{url}/fulfilment/start", headers=BUYER).status_code == 403  # buyer is not the supplier
    assert client.post(f"{url}/fulfilment/start", headers=SUP_B).status_code == 404  # stranger
    assert client.post(f"{url}/fulfilment/start", headers={**SUP_B, "X-Supplier-Id": SUP_REF}).status_code == 404
    assert client.post(f"{url}/fulfilment/start", headers=SUP_A).status_code == 403  # no verified supplier id
    assert client.post(f"{url}/fulfilment/start", headers={**SUP_A, "X-Supplier-Id": "other"}).status_code == 403
    assert client.post(f"{url}/fulfilment/start").status_code == 401
    assert client.post(f"{url}/fulfilment/start", headers=SUP_A_V).status_code == 200
    assert client.post(f"{url}/delivered", headers=BUYER).status_code == 403
    assert client.post(f"{url}/delivered", headers=SUP_B).status_code == 404
    assert client.post(f"{url}/confirm-receipt", headers=SUP_A_V).status_code == 403  # supplier cannot self-confirm
    assert client.post(f"{url}/confirm-receipt", headers=SUP_B).status_code == 404
    assert client.get(f"{url}/events", headers=SUP_B).status_code == 404
    assert client.post("/v1/deals/deal_nope/confirm-receipt", headers=BUYER).status_code == 404
    assert status(client, d) == "in_fulfilment"
    # wrong state: delivered / confirm before fulfilment
    d2 = make_deal(client)
    assert client.post(f"/v1/deals/{d2['id']}/delivered", headers=SUP_A_V).status_code == 409
    assert client.post(f"/v1/deals/{d2['id']}/confirm-receipt", headers=BUYER).status_code == 409


def test_reviews_unlock_after_payment(client):
    d = make_deal(client)
    assert client.post(f"/v1/deals/{d['id']}/reviews", json={"rating": 5}, headers=BUYER).status_code == 409
    cb(client, d, "deal_payment", other_open=["commission"])
    assert client.post(f"/v1/deals/{d['id']}/reviews", json={"rating": 5}, headers=BUYER).status_code == 409
    cb(client, d, "commission")
    assert client.post(f"/v1/deals/{d['id']}/reviews", json={"rating": 5}, headers=BUYER).status_code == 201
    # a refunded deal is no longer reviewable-for-new-deals
    d2 = make_deal(client)
    cb(client, d2)
    cb(client, d2, status="refunded")
    assert client.post(f"/v1/deals/{d2['id']}/reviews", json={"rating": 5}, headers=BUYER).status_code == 409
    # completed deals count towards the supplier summary
    d3 = make_deal(client)
    cb(client, d3)
    client.post(f"/v1/deals/{d3['id']}/fulfilment/start", headers=SUP_A_V)
    client.post(f"/v1/deals/{d3['id']}/confirm-receipt", headers=BUYER)
    assert client.get(f"/v1/suppliers/{SUP_REF}/review-summary").json()["completed_deals"] == 1


def test_event_log_is_immutable(client):
    d = make_deal(client)
    cb(client, d)

    async def run():
        async with client.app.state.service._sessions() as s:
            e = (await s.execute(select(DealEventRow))).scalars().first()
            e.action = "tampered"
            await s.commit()

    with pytest.raises(DealEventImmutable):
        client.portal.call(run)


def test_stale_paid_after_refund_of_same_invoice_is_ignored(client):
    d = make_deal(client)
    cb(client, d, "commission")
    assert cb(client, d, "commission", "refunded").json()["deal_status"] == "pending_payment"
    late = cb(client, d, "commission")  # reordered/replayed old 'paid' for the refunded invoice
    assert late.json()["outcome"] == "ignored" and late.json()["deal_status"] == "pending_payment"
    assert late.json()["payment"]["commission"] == "refunded"


# ---- deal lookup: GET /v1/deals, GET /v1/requests/{id}/deal ------------------------------------
def test_list_deals_authorization_matrix_and_pagination(client, clock):
    d1 = make_deal(client)
    clock.advance(minutes=1)
    d2 = make_deal(client)
    clock.advance(minutes=1)
    other = {"X-User-Id": "buyer2"}  # another buyer's deal must stay invisible to BUYER
    r = client.post("/v1/requests", json={"kind": "product", "title": "LED panel lights", "quantity": "1000",
                                          "unit": "piece", "destination": {"country_code": "IQ", "city": "Basra"}},
                    headers=other).json()
    off2 = new_offer(client, r["id"], SUP_B, "7.00")
    d3 = client.post(f"/v1/offers/{off2['id']}/accept", headers=other).json()

    def ids(role, headers, **q):
        resp = client.get("/v1/deals", params={"role": role, **q}, headers=headers)
        assert resp.status_code == 200, resp.text
        return [x["id"] for x in resp.json()["items"]], resp.json()

    assert ids("buyer", BUYER)[0] == [d2["id"], d1["id"]]  # newest first
    assert ids("any", BUYER)[0] == [d2["id"], d1["id"]]
    assert ids("supplier", BUYER)[0] == []  # a buyer is not a supplier
    assert ids("supplier", SUP_A)[0] == [d2["id"], d1["id"]]
    assert ids("buyer", SUP_A)[0] == []
    assert ids("any", SUP_B)[0] == [d3["id"]]
    assert ids("any", {"X-User-Id": "stranger"})[0] == []
    assert ids("buyer", other)[0] == [d3["id"]]
    item = client.get("/v1/deals", headers=BUYER).json()["items"][0]  # same JSON as GET /v1/deals/{id}
    assert item == client.get(f"/v1/deals/{item['id']}", headers=BUYER).json()
    assert ids("buyer", BUYER, status="paid")[0] == []
    assert len(ids("buyer", BUYER, status="pending_payment")[0]) == 2
    p1, b1 = ids("any", BUYER, page_size=1, page=1)
    p2, b2 = ids("any", BUYER, page_size=1, page=2)
    assert p1 + p2 == [d2["id"], d1["id"]] and b1["total"] == 2 and b2["page"] == 2
    assert ids("any", BUYER, page_size=1, page=3)[0] == []


def test_list_deals_same_timestamp_is_stable_and_validation(client):
    made = [make_deal(client)["id"] for _ in range(3)]  # frozen clock: identical created_at
    seen = []
    for pg in (1, 2, 3):
        seen += [x["id"] for x in client.get("/v1/deals", params={"page": pg, "page_size": 1}, headers=BUYER).json()["items"]]
    assert seen == sorted(made, reverse=True)
    assert client.get("/v1/deals", params={"role": "admin"}, headers=BUYER).status_code == 422
    assert client.get("/v1/deals", params={"status": "nope"}, headers=BUYER).status_code == 422
    assert client.get("/v1/deals", params={"page_size": 101}, headers=BUYER).status_code == 422
    assert client.get("/v1/deals").status_code == 401


def test_request_deal_buyer_only(client):
    req = new_request(client)
    assert client.get(f"/v1/requests/{req['id']}/deal", headers=BUYER).status_code == 404  # not awarded yet
    off = new_offer(client, req["id"], SUP_A_V, "10.00")
    deal = client.post(f"/v1/offers/{off['id']}/accept", headers=BUYER).json()
    r = client.get(f"/v1/requests/{req['id']}/deal", headers=BUYER)
    assert r.status_code == 200 and r.json() == deal
    for h in (SUP_A, SUP_A_V, SUP_B, {"X-User-Id": "stranger"}):
        assert client.get(f"/v1/requests/{req['id']}/deal", headers=h).status_code == 404
    assert client.get("/v1/requests/req_missing/deal", headers=BUYER).status_code == 404
    assert client.get(f"/v1/requests/{req['id']}/deal").status_code == 401


# ---- security-review-2026-10-g ----------------------------------------------------------------
def test_accept_huge_total_is_exact(client):
    req = new_request(client, quantity="99999999999999.9999")
    off = new_offer(client, req["id"], SUP_A, "99999999999999.9999")
    d = client.post(f"/v1/offers/{off['id']}/accept", headers=BUYER)
    assert d.status_code == 200, d.text  # was decimal.InvalidOperation (28-digit context) -> 500
    from decimal import Decimal, localcontext
    with localcontext() as ctx:
        ctx.prec = 80
        assert Decimal(d.json()["subtotal"]["amount"]) == (Decimal("99999999999999.9999") ** 2).quantize(Decimal("0.01"))
    # a large-but-storable total keeps exact cents
    req = new_request(client, quantity="12345678901.1234")
    off = new_offer(client, req["id"], SUP_A, "123456789.1234")
    d = client.post(f"/v1/offers/{off['id']}/accept", headers=BUYER).json()
    with localcontext() as ctx:
        ctx.prec = 80
        assert Decimal(d["subtotal"]["amount"]) == (Decimal("12345678901.1234") * Decimal("123456789.1234")).quantize(Decimal("0.01"))
        assert Decimal(d["supplier_net"]["amount"]) == Decimal(d["subtotal"]["amount"]) - Decimal(d["commission"]["amount"]["amount"])


def test_accept_expired_offer_even_if_sweep_is_stale(client, clock):
    req = new_request(client)
    off = new_offer(client, req["id"], SUP_A, valid_until="2026-10-01T13:00:00Z")
    client.get(f"/v1/requests/{req['id']}", headers=BUYER)  # sweep ran; nothing due yet
    clock.advance(hours=2)
    r = client.post(f"/v1/offers/{off['id']}/accept", headers=BUYER)
    assert r.status_code == 409


def test_double_accept_and_accept_after_close(client):
    req = new_request(client)
    o1, o2 = new_offer(client, req["id"], SUP_A), new_offer(client, req["id"], SUP_B)
    assert client.post(f"/v1/offers/{o1['id']}/accept", headers=BUYER).status_code == 200
    assert client.post(f"/v1/offers/{o1['id']}/accept", headers=BUYER).status_code == 409
    assert client.post(f"/v1/offers/{o2['id']}/accept", headers=BUYER).status_code == 409
    assert client.post(f"/v1/requests/{req['id']}/offers", headers=SUP_B, json={
        "price": {"amount": "1", "currency": "USD"}, "supplier_name": "x"}).status_code == 409


def test_offer_cap_per_supplier(client):
    req = new_request(client)
    for _ in range(5):
        new_offer(client, req["id"], SUP_A)
    r = client.post(f"/v1/requests/{req['id']}/offers", headers=SUP_A, json={
        "price": {"amount": "1", "currency": "USD"}, "supplier_name": "x"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "offer_limit_reached"
    new_offer(client, req["id"], SUP_B)  # other suppliers unaffected
