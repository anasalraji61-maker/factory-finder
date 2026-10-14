import json

import pytest
from conftest import ADMIN, BUYER, mk, post_event

from ff_payments import webhooks


def _ev(inv, typ="payment.confirmed", eid="evt_1", **kw):
    return {"event_id": eid, "type": typ, "invoice_id": inv["id"], **kw}


def _status(client, inv):
    return client.get(f"/v1/invoices/{inv['id']}", headers=BUYER).json()


def test_signature_unit():
    h = webhooks.sign("s", b"body", 1000)
    webhooks.verify("s", b"body", h, now_ts=1000, tolerance=300)
    webhooks.verify("s", b"body", h + ",v1=deadbeef", now_ts=1100, tolerance=300)  # rotation: any v1 matches
    for bad in (None, "", "garbage", "t=1000", "v1=ab", "t=x,v1=ab", webhooks.sign("other", b"body", 1000),
                webhooks.sign("s", b"bodY", 1000)):
        with pytest.raises(webhooks.InvalidSignature):
            webhooks.verify("s", b"body", bad, now_ts=1000, tolerance=300)
    with pytest.raises(webhooks.InvalidSignature) as e:
        webhooks.verify("s", b"body", h, now_ts=1301, tolerance=300)
    assert e.value.code == "stale_timestamp"
    with pytest.raises(webhooks.InvalidSignature):  # future timestamps are out of tolerance too
        webhooks.verify("s", b"body", h, now_ts=600, tolerance=300)


def test_confirmed_event_pays_once_and_is_idempotent(client):
    inv = mk(client).json()
    r = post_event(client, _ev(inv, tx_ref="tx9"))
    assert r.status_code == 200 and r.json() == {"status": "applied", "invoice_id": inv["id"], "invoice_status": "paid"}
    assert _status(client, inv)["tx_ref"] == "tx9"
    again = post_event(client, _ev(inv, tx_ref="tx9"))
    assert again.json()["status"] == "duplicate"
    # a NEW event id for an already paid invoice changes nothing and writes no second ledger group
    assert post_event(client, _ev(inv, eid="evt_2")).json()["status"] == "ignored"
    led = client.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=ADMIN).json()
    assert led["total"] == 2


def test_replay_of_valid_signed_body_is_rejected_as_duplicate(client):
    inv = mk(client).json()
    body = json.dumps(_ev(inv, "payment.confirming")).encode()
    sig = webhooks.sign("whsec-test", body, int(client.clock().timestamp()))
    h = {"X-FF-Signature": sig}
    assert client.post("/v1/payments/webhooks/mock", content=body, headers=h).json()["status"] == "applied"
    assert client.post("/v1/payments/webhooks/mock", content=body, headers=h).json()["status"] == "duplicate"


def test_bad_signature_stale_and_missing_secret(client, clock):
    inv = mk(client).json()
    assert post_event(client, _ev(inv), secret="wrong").status_code == 401
    assert post_event(client, _ev(inv), sig="").status_code == 401
    r = post_event(client, _ev(inv), ts=int(clock().timestamp()) - 301)
    assert r.status_code == 401 and r.json()["error"]["code"] == "stale_timestamp"
    assert _status(client, inv)["status"] == "awaiting_payment"
    assert post_event(client, _ev(inv), provider="usdt_tron").status_code == 503  # no secret configured
    assert post_event(client, _ev(inv), provider="nope").status_code == 404


def test_malformed_events(client):
    inv = mk(client).json()
    assert post_event(client, {"event_id": "e", "type": "payment.bogus", "invoice_id": inv["id"]}).status_code == 400
    assert post_event(client, {"type": "payment.confirmed"}).status_code == 400
    assert post_event(client, _ev(inv, eid="e3", amount={"amount": 5.5, "currency": "USD"})).status_code == 400
    assert post_event(client, _ev({"id": "inv_missing"})).status_code == 404
    raw = b"not json"
    sig = webhooks.sign("whsec-test", raw, int(client.clock().timestamp()))
    assert client.post("/v1/payments/webhooks/mock", content=raw, headers={"X-FF-Signature": sig}).status_code == 400


def test_lookup_by_provider_ref_and_status_progression(client):
    inv = mk(client).json()
    r = post_event(client, {"event_id": "a", "type": "payment.confirming", "provider_ref": inv["provider_ref"],
                            "confirmations": 3})
    assert r.json()["invoice_status"] == "confirming" and _status(client, inv)["confirmations"] == 3
    r = post_event(client, {"event_id": "b", "type": "payment.confirmed", "provider_ref": inv["provider_ref"],
                            "amount": {"amount": "375.00", "currency": "USD"}})
    assert r.json()["invoice_status"] == "paid"


def test_wrong_amount_never_settles(client):
    inv = mk(client).json()
    r = post_event(client, _ev(inv, amount={"amount": "374.99", "currency": "USD"}))
    assert r.json()["status"] == "ignored" and _status(client, inv)["status"] == "awaiting_payment"
    r = post_event(client, _ev(inv, eid="e2", amount={"amount": "375.00", "currency": "EUR"}))
    assert r.json()["status"] == "ignored"


def test_illegal_transitions_are_acknowledged_not_applied(client):
    inv = mk(client).json()
    client.post(f"/v1/invoices/{inv['id']}/cancel", headers=BUYER)
    r = post_event(client, _ev(inv))  # paid after cancel: cannot move a failed invoice
    assert r.status_code == 200 and r.json()["status"] == "ignored"
    assert _status(client, inv)["status"] == "failed"
    assert client.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=ADMIN).json()["total"] == 0


def test_failed_and_expired_events(client):
    a, b = mk(client).json(), mk(client, "deal_payment").json()
    assert post_event(client, _ev(a, "payment.failed", "f1")).json()["invoice_status"] == "failed"
    assert post_event(client, _ev(b, "payment.expired", "x1")).json()["invoice_status"] == "expired"
