import json
from collections import defaultdict
from decimal import Decimal

import pytest
from conftest import ADMIN, BUYER, DEAL, OTHER, SUPPLIER, mk
from sqlalchemy import select

from ff_payments.db import LedgerEntryRow, LedgerImmutable


def test_deal_owner_creates_commission_invoice_from_deal(client):
    r = mk(client)
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["status"] == "awaiting_payment" and inv["kind"] == "commission"
    assert inv["amount"] == {"amount": "375.00", "currency": "USD"}
    assert inv["payer_user_id"] == "buyer1" and inv["payee"] == "platform"
    assert inv["provider"] == "mock" and inv["pay_address"] and inv["memo"].startswith("FF-")
    assert isinstance(inv["amount"]["amount"], str)


def test_deal_payment_pays_supplier_and_is_idempotent(client):
    a = mk(client, "deal_payment")
    assert a.status_code == 201 and a.json()["payee"] == "sup1"
    assert a.json()["amount"]["amount"] == "12500.00"
    b = mk(client, "deal_payment")
    assert b.status_code == 200 and b.json()["id"] == a.json()["id"]


def test_non_owner_cannot_create_and_overrides_are_admin_only(client):
    assert mk(client, headers=OTHER).status_code == 404
    assert mk(client, headers=SUPPLIER).status_code == 404  # supplier is not the payer
    assert mk(client).status_code == 201
    r = mk(client, "deal_payment", amount={"amount": "1.00", "currency": "USD"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "admin_required"
    assert mk(client, "deal_payment", payee="mallory").status_code == 403
    assert client.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"}).status_code == 401
    assert mk(client, deal_id="nope").status_code == 404


def test_money_must_be_decimal_strings(client):
    bad = {"deal_id": "d", "kind": "commission", "payer_user_id": "u", "payee": "platform"}
    for amount in ({"amount": 10.5, "currency": "USD"}, {"amount": "10.555", "currency": "USD"},
                   {"amount": "-1", "currency": "USD"}, {"amount": "0", "currency": "USD"},
                   {"amount": "1e3", "currency": "USD"}, {"amount": "NaN", "currency": "USD"}):
        r = client.post("/v1/invoices", json={**bad, "amount": amount}, headers=ADMIN)
        assert r.status_code == 422, (amount, r.text)


def test_admin_invoice_with_commission_basis_uses_rfq_rule(client):
    body = {"deal_id": "d9", "kind": "commission", "payer_user_id": "u1", "payee": "platform",
            "commission_basis": {"subtotal": {"amount": "1000.50", "currency": "USD"}, "listing_kind": "product"}}
    r = client.post("/v1/invoices", json=body, headers=ADMIN)
    assert r.status_code == 201 and r.json()["amount"]["amount"] == "30.02"
    body.update(deal_id="d10", commission_basis={"subtotal": {"amount": "100", "currency": "USD"},
                                                  "listing_kind": "production_line"})
    assert client.post("/v1/invoices", json=body, headers=ADMIN).json()["amount"]["amount"] == "25.00"


def test_idor_get_list_cancel_ledger_refund(client):
    inv = mk(client).json()
    url = f"/v1/invoices/{inv['id']}"
    assert client.get(url, headers=BUYER).status_code == 200
    assert client.get(url, headers=ADMIN).status_code == 200
    assert client.get(url, headers=OTHER).status_code == 404
    assert client.get(url).status_code == 401
    assert client.post(url + "/cancel", headers=OTHER).status_code == 404
    assert client.post(url + "/refund", headers=BUYER).status_code == 403
    assert client.post(url + "/refund", headers={"X-User-Id": "admin", "X-Admin-Token": "wrong"}).status_code == 403
    assert client.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=BUYER).status_code == 403
    assert client.get("/v1/invoices", params={"deal_id": "deal_1"}, headers=OTHER).json()["total"] == 0
    assert client.get("/v1/invoices", params={"deal_id": "deal_1"}, headers=BUYER).json()["total"] == 1
    assert client.get("/v1/invoices", params={"deal_id": "deal_1"}, headers=ADMIN).json()["total"] == 1
    # supplier (payee of a deal_payment) sees that invoice but cannot cancel it
    dp = mk(client, "deal_payment").json()
    assert client.get(f"/v1/invoices/{dp['id']}", headers=SUPPLIER).status_code == 200
    assert client.post(f"/v1/invoices/{dp['id']}/cancel", headers=SUPPLIER).status_code == 404
    assert client.get("/v1/invoices", headers=SUPPLIER).json()["total"] == 1


def test_admin_disabled_without_token_setting(clock):
    from conftest import make_settings
    from fastapi.testclient import TestClient

    from ff_payments.main import create_app
    with TestClient(create_app(make_settings(admin_token=None), clock=clock)) as c:
        assert c.get("/v1/ledger", params={"invoice_id": "x"}, headers={"X-Admin-Token": ""}).status_code == 403
        assert c.get("/v1/invoices", headers={"X-Admin-Token": "anything"}).status_code == 401


def test_cancel_and_status_machine(client):
    inv = mk(client).json()
    r = client.post(f"/v1/invoices/{inv['id']}/cancel", headers=BUYER)
    assert r.status_code == 200 and r.json()["status"] == "failed" and r.json()["status_reason"] == "cancelled"
    again = client.post(f"/v1/invoices/{inv['id']}/cancel", headers=BUYER)
    assert again.status_code == 409 and again.json()["error"]["code"] == "invalid_invoice_transition"
    assert client.post(f"/v1/invoices/{inv['id']}/refund", headers=ADMIN).status_code == 409
    # a cancelled invoice is closed: a new one may be created for the same deal
    assert mk(client).status_code == 201
    # confirming / paid invoices cannot be cancelled
    p = mk(client, "deal_payment").json()
    client.provider.confirm(p["provider_ref"])
    client.post("/v1/payments/sweep", headers=ADMIN)
    assert client.post(f"/v1/invoices/{p['id']}/cancel", headers=BUYER).status_code == 409


def test_sweep_polls_provider_and_settles_with_balanced_ledger(client):
    inv = mk(client).json()
    client.provider.seen(inv["provider_ref"], confirmations=2)
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["updated"] == 1
    assert client.get(f"/v1/invoices/{inv['id']}", headers=BUYER).json()["status"] == "confirming"
    assert client.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=ADMIN).json()["total"] == 0
    client.provider.confirm(inv["provider_ref"], tx_ref="tx1", confirmations=20)
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["updated"] == 1
    got = client.get(f"/v1/invoices/{inv['id']}", headers=BUYER).json()
    assert got["status"] == "paid" and got["tx_ref"] == "tx1" and got["paid_at"]
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["updated"] == 0  # idempotent
    led = client.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=ADMIN).json()
    assert led["total"] == 2
    by = {e["direction"]: e for e in led["items"]}
    assert by["debit"]["account"] == "clearing:mock" and by["credit"]["account"] == "revenue:commission"
    assert by["debit"]["amount"] == by["credit"]["amount"] == {"amount": "375.00", "currency": "USD"}


def test_deal_payment_credits_payee_payable(client):
    inv = mk(client, "deal_payment").json()
    client.provider.confirm(inv["provider_ref"])
    client.post("/v1/payments/sweep", headers=ADMIN)
    led = client.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=ADMIN).json()["items"]
    assert {e["account"] for e in led} == {"clearing:mock", "payable:sup1"}


def test_refund_appends_reversal_and_every_group_balances(client):
    inv = mk(client).json()
    client.provider.confirm(inv["provider_ref"])
    client.post("/v1/payments/sweep", headers=ADMIN)
    r = client.post(f"/v1/invoices/{inv['id']}/refund", headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "refunded"
    assert client.post(f"/v1/invoices/{inv['id']}/refund", headers=ADMIN).status_code == 409
    items = client.get("/v1/ledger", params={"invoice_id": inv["id"]}, headers=ADMIN).json()["items"]
    assert len(items) == 4 and {e["reason"] for e in items} == {"payment", "refund"}
    groups: dict[str, Decimal] = defaultdict(Decimal)
    nets: dict[str, Decimal] = defaultdict(Decimal)
    for e in items:
        v = Decimal(e["amount"]["amount"])
        sign = 1 if e["direction"] == "debit" else -1
        groups[e["group_id"]] += sign * v
        nets[e["account"]] += sign * v
    assert len(groups) == 2 and all(v == 0 for v in groups.values())
    assert all(v == 0 for v in nets.values())  # refund fully reverses the payment


def test_ledger_rows_are_immutable(client):
    inv = mk(client).json()
    client.provider.confirm(inv["provider_ref"])
    client.post("/v1/payments/sweep", headers=ADMIN)

    async def tamper(delete: bool):
        async with client.app.state.service.sessions() as s:
            row = (await s.execute(select(LedgerEntryRow))).scalars().first()
            if delete:
                await s.delete(row)
            else:
                row.amount = "0.01"
            await s.commit()

    for delete in (False, True):
        with pytest.raises(LedgerImmutable):
            client.portal.call(tamper, delete)


def test_expiry_lazy_and_sweep(client, clock):
    a, b = mk(client).json(), mk(client, "deal_payment").json()
    clock.advance(minutes=59)
    assert client.get(f"/v1/invoices/{a['id']}", headers=BUYER).json()["status"] == "awaiting_payment"
    clock.advance(minutes=2)
    got = client.get(f"/v1/invoices/{a['id']}", headers=BUYER).json()
    assert got["status"] == "expired" and got["status_reason"] == "expired"
    assert client.post("/v1/payments/sweep", headers=ADMIN).json()["expired"] == 1  # b via sweep
    assert client.get(f"/v1/invoices/{b['id']}", headers=BUYER).json()["status"] == "expired"
    assert client.post(f"/v1/invoices/{a['id']}/cancel", headers=BUYER).status_code == 409
    assert mk(client).status_code == 201  # expired invoice does not block a new one


def test_confirming_invoice_does_not_expire(client, clock):
    inv = mk(client).json()
    client.provider.seen(inv["provider_ref"])
    client.post("/v1/payments/sweep", headers=ADMIN)
    clock.advance(hours=5)
    assert client.get(f"/v1/invoices/{inv['id']}", headers=BUYER).json()["status"] == "confirming"


def test_admin_custom_ttl(client, clock):
    body = {"deal_id": "dx", "kind": "deal_payment", "payer_user_id": "u", "payee": "s",
            "amount": {"amount": "5.00", "currency": "USD"}, "expires_in_minutes": 5}
    inv = client.post("/v1/invoices", json=body, headers=ADMIN).json()
    clock.advance(minutes=6)
    assert client.get(f"/v1/invoices/{inv['id']}", headers=ADMIN).json()["status"] == "expired"


def test_provider_off_rejects_creation_but_reads_work(clock):
    from conftest import make_settings
    from fastapi.testclient import TestClient

    from ff_payments.clients.deals import MockDealClient
    from ff_payments.main import create_app
    with TestClient(create_app(make_settings(provider="off"), deals=MockDealClient({"deal_1": DEAL}), clock=clock)) as c:
        r = mk(c)
        assert r.status_code == 503 and r.json()["error"]["code"] == "provider_disabled"
        assert c.get("/v1/invoices", headers=BUYER).status_code == 200
        assert c.post("/v1/payments/sweep", headers=ADMIN).status_code == 200


def test_validation_and_unknown_fields(client):
    assert client.post("/v1/invoices", json={"deal_id": "d", "kind": "bogus"}, headers=BUYER).status_code == 422
    assert client.post("/v1/invoices", json={"deal_id": "d", "kind": "commission", "x": 1}, headers=BUYER).status_code == 422
    assert client.get("/v1/ledger", headers=ADMIN).status_code == 422
    assert client.get("/v1/invoices/inv_missing", headers=BUYER).status_code == 404


def test_internal_token_guard_and_health(clock):
    from conftest import make_settings
    from fastapi.testclient import TestClient

    from ff_payments.main import create_app
    with TestClient(create_app(make_settings(internal_token="tok"), clock=clock)) as c:
        assert c.get("/health").status_code == 200 and c.get("/ready").status_code == 200
        assert c.get("/v1/invoices", headers={"X-User-Id": "u"}).status_code == 401
        assert c.get("/v1/invoices", headers={"X-User-Id": "u", "X-Internal-Token": "tok"}).status_code == 200
        # webhooks use HMAC instead of the internal token (unsigned -> 401 from the signature check)
        r = c.post("/v1/payments/webhooks/mock", content=b"{}")
        assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_signature"


def test_invoice_json_carries_no_float_numbers(client):
    inv = mk(client).json()
    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        else:
            assert not isinstance(x, float)
    walk(inv)
    assert json.dumps(inv)
