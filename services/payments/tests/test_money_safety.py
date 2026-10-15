"""Late / wrong-amount money is never silently lost; USDT exactness; ledger per deal; privacy; webhook + admin auth."""

import hmac
import json
from decimal import Decimal

import httpx
import pytest
from conftest import (
    ADMIN,
    BUYER,
    DEAL,
    OTHER,
    SUPPLIER,
    WH_SECRET,
    Clock,
    make_settings,
    mk,
    post_event,
)
from fastapi.testclient import TestClient
from test_usdt_tron_review import ADDR, CONTRACT, T0, Chain, ExplorerClient, UsdtTronProvider, tx

from ff_payments import webhooks
from ff_payments.clients.deals import MockDealClient
from ff_payments.main import create_app
from ff_payments.providers.usdt_tron import amount_with_suffix

MICRO = Decimal("0.000001")


def _get(c, inv, h=BUYER):
    return c.get(f"/v1/invoices/{inv['id']}", headers=h).json()


def _ledger(c, inv):
    return c.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=ADMIN).json()["total"]


def _review(c):
    return c.get("/v1/payments/review", headers=ADMIN).json()


# ---- late payment ------------------------------------------------------------------------
def test_webhook_paid_after_expiry_is_flagged_not_settled_not_lost(client, clock):
    inv = mk(client).json()
    clock.advance(minutes=61)
    r = post_event(client, {"event_id": "late1", "type": "payment.confirmed", "invoice_id": inv["id"], "tx_ref": "txL"})
    assert r.json() == {"status": "review", "invoice_id": inv["id"], "invoice_status": "expired"}
    got = _get(client, inv)
    assert got["status"] == "expired" and got["status_reason"] == "late_payment_review" and got["tx_ref"] == "txL"
    assert _ledger(client, inv) == 0  # not auto-settled
    rv = _review(client)
    assert rv["total"] == 1 and rv["items"][0]["id"] == inv["id"]
    assert post_event(client, {"event_id": "late1", "type": "payment.confirmed", "invoice_id": inv["id"]}).json()["status"] == "duplicate"
    assert client.get("/v1/payments/review", headers=BUYER).status_code == 403


def test_sweep_flags_late_transfer_for_expired_invoice_and_prune_keeps_evidence(client, clock):
    inv = mk(client).json()
    clock.advance(minutes=61)
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["expired"] == 1
    client.provider.confirm(inv["provider_ref"], tx_ref="late_tx")
    out = client.post("/v1/payments/sweep", headers=ADMIN).json()
    assert out["late_flagged"] == 1 and _get(client, inv)["status_reason"] == "late_payment_review"
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["late_flagged"] == 0  # flagged once
    clock.advance(days=400)  # retention windows pass: flagged evidence survives
    client.post("/v1/payments/sweep", headers=ADMIN)
    assert _review(client)["total"] == 1 and _get(client, inv)["tx_ref"] == "late_tx"


def test_same_late_tx_cannot_flag_two_invoices(client, clock):
    a = mk(client).json()
    clock.advance(minutes=61)
    client.post("/v1/payments/sweep", headers=ADMIN)
    b = mk(client, "deal_payment").json()
    clock.advance(minutes=61)
    client.post("/v1/payments/sweep", headers=ADMIN)
    client.provider.confirm(a["provider_ref"], tx_ref="same")
    client.provider.confirm(b["provider_ref"], tx_ref="same")
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["late_flagged"] == 1
    assert _review(client)["total"] == 1


def test_paid_after_cancel_is_flagged(client):
    inv = mk(client).json()
    client.post(f"/v1/invoices/{inv['id']}/cancel", headers=BUYER)
    assert post_event(client, {"event_id": "c1", "type": "payment.confirmed", "invoice_id": inv["id"]}).json()["status"] == "review"
    assert _get(client, inv)["status"] == "failed" and _ledger(client, inv) == 0


def test_wrong_amount_event_is_flagged_and_later_correct_payment_clears_flag(client):
    inv = mk(client).json()
    r = post_event(client, {"event_id": "u", "type": "payment.confirmed", "invoice_id": inv["id"],
                            "amount": {"amount": "374.99", "currency": "USD"}})
    assert r.json()["status"] == "review"
    got = _get(client, inv)
    assert got["status"] == "awaiting_payment" and got["status_reason"] == "amount_mismatch_review"
    assert _review(client)["total"] == 1
    r = post_event(client, {"event_id": "ok", "type": "payment.confirmed", "invoice_id": inv["id"],
                            "amount": {"amount": "375.00", "currency": "USD"}})
    assert r.json()["invoice_status"] == "paid"
    assert _get(client, inv)["status_reason"] is None and _review(client)["total"] == 0 and _ledger(client, inv) == 2


# ---- USDT thresholds / suffix ------------------------------------------------------------
def _tron_app(chain, clock):
    ex = ExplorerClient("https://explorer.invalid", transport=httpx.MockTransport(chain.handler))
    p = UsdtTronProvider(address=ADDR, contract=CONTRACT, explorer=ex, min_confirmations=1)
    return create_app(make_settings(provider="off"), provider=p, clock=clock,
                      deals=MockDealClient({"deal_1": DEAL}))


def test_usdt_one_micro_under_or_over_never_settles_exact_does():
    clock, ch = Clock(), Chain()
    with TestClient(_tron_app(ch, clock)) as c:
        inv = mk(c).json()
        pay = Decimal(inv["pay_amount"]["amount"])
        assert pay.as_tuple().exponent == -6 and Decimal("375.000001") <= pay <= Decimal("375.000999")
        micro = int(pay * 1_000_000)
        ch.latest = 1000
        for bad, tid in ((micro - 1, "u"), (micro + 1, "o"), (micro * 10, "x")):
            ch.txs = [tx(bad, tid=tid, ts=T0 + 1000)]
            c.post("/v1/payments/sweep", headers=ADMIN)
            assert _get(c, inv)["status"] == "awaiting_payment"
        ch.txs = [tx(micro, tid="good", ts=T0 + 1000)]
        c.post("/v1/payments/sweep", headers=ADMIN)
        assert _get(c, inv)["status"] == "paid" and _ledger(c, inv) == 2


def test_usdt_suffixes_are_unique_among_open_invoices_and_bounded():
    taken: set[str] = set()
    for i in range(999):
        amt = amount_with_suffix(Decimal("10.00"), f"inv_{i}", frozenset(taken))
        assert amt not in {Decimal(t) for t in taken}
        assert Decimal("10.00") < amt <= Decimal("10.000999") and amt == amt.quantize(MICRO)
        taken.add(format(amt, "f"))
    assert len(taken) == 999
    with pytest.raises(Exception, match="suffix"):
        amount_with_suffix(Decimal("10.00"), "inv_x", frozenset(taken))


def test_usdt_late_transfer_flagged_for_review_via_sweep():
    clock, ch = Clock(), Chain()
    with TestClient(_tron_app(ch, clock)) as c:
        inv = mk(c).json()
        micro = int(Decimal(inv["pay_amount"]["amount"]) * 1_000_000)
        clock.advance(minutes=61)
        c.post("/v1/payments/sweep", headers=ADMIN)
        assert _get(c, inv)["status"] == "expired"
        ch.txs, ch.latest = [tx(micro, tid="late", block=900, ts=T0 + 7_200_000)], 1000
        assert c.post("/v1/payments/sweep", headers=ADMIN).json()["late_flagged"] == 1
        assert _get(c, inv)["status_reason"] == "late_payment_review" and _get(c, inv)["status"] == "expired"


# ---- refunds / commission ledger ---------------------------------------------------------
def test_refund_twice_is_409_and_unpaid_cannot_be_refunded(client):
    inv = mk(client).json()
    assert client.post(f"/v1/invoices/{inv['id']}/refund", headers=ADMIN).status_code == 409
    client.provider.confirm(inv["provider_ref"])
    client.post("/v1/payments/sweep", headers=ADMIN)
    assert client.post(f"/v1/invoices/{inv['id']}/refund", headers=ADMIN).status_code == 200
    assert client.post(f"/v1/invoices/{inv['id']}/refund", headers=ADMIN).status_code == 409
    led = client.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=ADMIN).json()["items"]
    assert len(led) == 4
    net: dict[str, Decimal] = {}
    for e in led:
        net[e["account"]] = net.get(e["account"], Decimal(0)) + (1 if e["direction"] == "debit" else -1) * Decimal(e["amount"]["amount"])
    assert all(v == 0 for v in net.values())


def test_commission_ledger_per_deal_net_of_refund(client):
    assert client.get("/v1/ledger/deals/deal_1/commission", headers=BUYER).status_code == 403
    assert client.get("/v1/ledger/deals/deal_1/commission", headers=ADMIN).json() == {"deal_id": "deal_1", "items": []}
    com, dp = mk(client).json(), mk(client, "deal_payment").json()
    client.provider.confirm(com["provider_ref"], tx_ref="t1")
    client.provider.confirm(dp["provider_ref"], tx_ref="t2")
    client.post("/v1/payments/sweep", headers=ADMIN)
    got = client.get("/v1/ledger/deals/deal_1/commission", headers=ADMIN).json()
    assert got["items"] == [{"currency": "USD", "earned": "375.00", "refunded": "0", "net": "375.00"}]  # payable leg excluded
    client.post(f"/v1/invoices/{com['id']}/refund", headers=ADMIN)
    got = client.get("/v1/ledger/deals/deal_1/commission", headers=ADMIN).json()
    assert got["items"][0]["net"] == "0.00" and got["items"][0]["refunded"] == "375.00"


# ---- privacy: export vs retained legal ledger --------------------------------------------
def test_erase_keeps_financial_records_and_export_never_leaks_ledger_or_others():
    tok = {"X-Internal-Token": "s3cret"}
    clock = Clock()
    app = create_app(make_settings(internal_token="s3cret"), deals=MockDealClient({"deal_1": DEAL}), clock=clock)
    with TestClient(app, headers=tok) as c:
        inv = mk(c, memo="secret note").json()
        c.delete("/v1/internal/users/buyer1/data")
        assert _get(c, inv)["user_memo"] is None
        assert _get(c, inv)["amount"] == inv["amount"]
        stranger = c.post("/v1/internal/users/nobody/export").json()
        assert stranger["data"]["invoices"] == [] and stranger["truncated"] is False
        assert c.delete("/v1/internal/users/nobody/data").json()["counts"] == {"memos_cleared": 0}


# ---- webhook signature -------------------------------------------------------------------
def test_signature_uses_constant_time_compare(monkeypatch):
    calls = []
    real = hmac.compare_digest
    monkeypatch.setattr(webhooks.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    h = webhooks.sign("s", b"x", 100) + ",v1=bad1,v1=bad2"
    webhooks.verify("s", b"x", h, now_ts=100, tolerance=300)
    assert len(calls) == 3  # every candidate compared, no early exit


def test_timestamp_tolerance_boundaries_and_replay_across_event_ids(client, clock):
    inv = mk(client).json()
    now = int(clock().timestamp())
    ev = {"type": "payment.confirming", "invoice_id": inv["id"]}
    assert post_event(client, {**ev, "event_id": "b1"}, ts=now - 300).status_code == 200  # edge accepted
    assert post_event(client, {**ev, "event_id": "b2"}, ts=now - 301).status_code == 401
    assert post_event(client, {**ev, "event_id": "b3"}, ts=now + 301).status_code == 401
    # a captured, validly signed old body cannot be re-timestamped without the secret
    raw = json.dumps({**ev, "event_id": "b4"}).encode()
    sig = webhooks.sign(WH_SECRET, raw, now)
    forged = "t=" + str(now + 5) + "," + sig.split(",", 1)[1]
    assert client.post("/v1/payments/webhooks/mock", content=raw, headers={"X-FF-Signature": forged}).status_code == 401
    assert post_event(client, {**ev, "event_id": "b4"}, ts=now).status_code == 200
    assert post_event(client, {**ev, "event_id": "b4"}, ts=now).json()["status"] == "duplicate"


# ---- admin auth matrix -------------------------------------------------------------------
ADMIN_ROUTES = [
    ("POST", "/v1/invoices/inv_x/refund"), ("GET", "/v1/ledger?invoice_id=x"), ("POST", "/v1/payments/sweep"),
    ("GET", "/v1/payments/outbox"), ("POST", "/v1/payments/outbox/obx/requeue"), ("GET", "/v1/payments/review"),
    ("GET", "/v1/ledger/deals/deal_1/commission"),
]


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_admin_matrix(client, method, path):
    for headers in ({}, BUYER, SUPPLIER, OTHER, {"X-Admin-Token": "wrong"}, {"X-User-Id": "u", "X-Admin-Token": ""},
                    {"X-Admin-Token": "admin-secret-test "}):
        assert client.request(method, path, headers=headers).status_code in (401, 403), headers
    assert client.request(method, path, headers=ADMIN).status_code not in (401, 403)
