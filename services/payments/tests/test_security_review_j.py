"""Security review 2026-10-j: deal-state gate, zero-decimal commission."""

from decimal import Decimal

import pytest
from conftest import BUYER, DEAL

from ff_payments.domain.commission import compute_commission
from ff_payments.domain.enums import ListingKind


@pytest.mark.parametrize("deal_status", ["refunded", "disputed"])
def test_no_new_invoice_for_a_dead_deal(client, deal_status):
    """A refunded/disputed deal must not take fresh money (the payer would pay for a deal that can never settle)."""
    client.deals.deals["deal_1"] = {**DEAL, "status": deal_status}
    for kind in ("deal_payment", "commission"):
        r = client.post("/v1/invoices", json={"deal_id": "deal_1", "kind": kind}, headers=BUYER)
        assert r.status_code == 409, (kind, r.text)
        assert r.json()["error"]["code"] == "deal_not_payable"


def test_live_deal_states_still_payable(client):
    for st in ("pending_payment", "paid"):
        client.deals.deals["deal_1"] = {**DEAL, "status": st}
        assert client.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"},
                           headers=BUYER).status_code in (200, 201)


def test_zero_decimal_currency_commission_is_whole_units():
    """IQD/JPY have no minor unit: must match rfq (whole units) or rfq rejects the paid callback as amount_mismatch."""
    c = compute_commission(Decimal("1000000"), "IQD", ListingKind.PRODUCT)
    assert c.min_fee_applied and c.amount == Decimal("32895") and c.amount == c.amount.to_integral_value()
    c = compute_commission(Decimal("10000000"), "IQD", ListingKind.PRODUCT)  # 3% = 300000 exactly
    assert c.amount == Decimal("300000") and not c.min_fee_applied
    c = compute_commission(Decimal("1234567"), "JPY", ListingKind.PRODUCT)  # 37037.01 -> 37037
    assert c.amount == Decimal("37037")


def _amountless(client, event_id):
    from conftest import post_event
    inv = client.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"}, headers=BUYER).json()
    r = post_event(client, {"event_id": event_id, "type": "payment.confirmed", "invoice_id": inv["id"]})
    got = client.get(f"/v1/invoices/{inv['id']}", headers=BUYER).json()
    return r.json(), got


def test_amountless_confirmed_settles_by_default(client):
    res, got = _amountless(client, "na1")
    assert res["status"] == "applied" and got["status"] == "paid"


def test_require_webhook_amount_sends_amountless_confirmed_to_review(clock, provider):
    from conftest import make_settings
    from fastapi.testclient import TestClient

    from ff_payments.clients.deals import MockDealClient
    from ff_payments.main import create_app
    deals = MockDealClient({"deal_1": DEAL})
    app = create_app(make_settings(require_webhook_amount=True), provider=provider, deals=deals, clock=clock)
    with TestClient(app) as c:
        c.provider, c.clock, c.deals = provider, clock, deals
        res, got = _amountless(c, "na2")
        assert res["status"] == "review" and got["status"] != "paid"
        from conftest import post_event
        ok = post_event(c, {"event_id": "na3", "type": "payment.confirmed", "invoice_id": got["id"],
                            "amount": got["amount"] and {"amount": got["amount"]["amount"], "currency": got["amount"]["currency"]}})
        assert ok.json()["invoice_status"] == "paid"  # a correct amount still settles
