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


def cb(client, deal, kind="deal_payment", status="paid", other_open=(), event_id=None, amount=None, headers=None):
    N[0] += 1
    m = amount or (deal["subtotal"] if kind == "deal_payment" else deal["commission"]["amount"])
    body = {"invoice_id": f"inv_{kind}", "kind": kind, "status": status, "amount": m,
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
    assert cb(client, d, "commission").json()["deal_status"] == "paid"
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
