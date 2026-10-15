from decimal import Decimal

import httpx
import pytest
from conftest import ADMIN, BUYER, DEAL, Clock, make_settings
from fastapi.testclient import TestClient

from ff_payments.clients.deals import MockDealClient
from ff_payments.main import create_app
from ff_payments.providers.usdt_tron import (
    ExplorerClient,
    ProviderNotConfigured,
    UsdtTronProvider,
    amount_with_suffix,
)

ADDR = "TNPeeaaFB7K9cmo4uQpcU32zGK8G1NYqeL"
CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"


class Chain:
    """Fake explorer: list of incoming transfers + latest block."""

    def __init__(self):
        self.txs: list[dict] = []
        self.latest = 1000
        self.calls: list[httpx.Request] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        if req.url.path.endswith("/blocks/latest"):
            return httpx.Response(200, json={"data": [{"block_number": self.latest}]})
        if "/transactions/trc20" in req.url.path:
            return httpx.Response(200, json={"data": self.txs})
        return httpx.Response(404)


def make(chain: Chain, **over):
    explorer = ExplorerClient("https://explorer.invalid", "key-from-env", transport=httpx.MockTransport(chain.handler))
    prov = UsdtTronProvider(address=ADDR, contract=CONTRACT, explorer=explorer, min_confirmations=20)
    clock = Clock()
    app = create_app(make_settings(provider="off", **over), provider=prov,
                     deals=MockDealClient({"deal_1": DEAL}), clock=clock)
    return app, clock


def tx(value_micro: int, block: int, tid="tx_abc"):
    return {"transaction_id": tid, "value": str(value_micro), "block_number": block,
            "block_timestamp": 10**13, "token_info": {"address": CONTRACT}}


def test_suffix_is_unique_deterministic_and_bounded():
    a = amount_with_suffix(Decimal("375.00"), "inv_1", frozenset())
    assert a == amount_with_suffix(Decimal("375.00"), "inv_1", frozenset())
    assert Decimal("375.000001") <= a <= Decimal("375.000999")
    b = amount_with_suffix(Decimal("375.00"), "inv_1", frozenset({format(a, "f")}))
    assert b != a and Decimal("375.000001") <= b <= Decimal("375.000999")
    full = frozenset(format(Decimal("375.00") + Decimal(i) * Decimal("0.000001"), "f") for i in range(1, 1000))
    with pytest.raises(ProviderNotConfigured):
        amount_with_suffix(Decimal("375.00"), "inv_1", full)


def test_invoice_gets_address_and_unique_pay_amount_then_confirms_by_threshold():
    chain = Chain()
    app, _ = make(chain)
    with TestClient(app) as c:
        a = c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"}, headers=BUYER).json()
        b = c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "deal_payment"}, headers=BUYER).json()
        assert a["pay_address"] == ADDR and a["pay_url"] is None and a["provider"] == "usdt_tron"
        pa = Decimal(a["pay_amount"]["amount"])
        assert a["pay_amount"]["currency"] == "USDT" and Decimal("375.000001") <= pa <= Decimal("375.000999")
        assert a["amount"]["amount"] == "375.00"  # the invoice itself stays in USD
        # nothing on chain yet
        assert c.post("/v1/payments/sweep", headers=ADMIN).json()["updated"] == 0
        micro = int(pa * 1_000_000)
        chain.txs = [tx(micro + 7, 990, "wrong"), tx(micro, 995)]  # only the exact amount matches
        chain.latest = 1000  # 6 confirmations < 20
        assert c.post("/v1/payments/sweep", headers=ADMIN).json()["updated"] == 1
        got = c.get(f"/v1/invoices/{a['id']}", headers=BUYER).json()
        assert got["status"] == "confirming" and got["confirmations"] == 6 and got["tx_ref"] == "tx_abc"
        assert c.get(f"/v1/invoices/{b['id']}", headers=BUYER).json()["status"] == "awaiting_payment"
        chain.latest = 1014  # 20 confirmations
        assert c.post("/v1/payments/sweep", headers=ADMIN).json()["updated"] == 1
        assert c.get(f"/v1/invoices/{a['id']}", headers=BUYER).json()["status"] == "paid"
        assert c.get("/v1/ledger", params={"invoice_id": a["id"]}, headers=ADMIN).json()["total"] == 2
    keys = [r.headers.get("tron-pro-api-key") for r in chain.calls]
    assert keys and all(k == "key-from-env" for k in keys)  # key only from env, sent as header, never in URL
    assert all("key-from-env" not in str(r.url) for r in chain.calls)


def test_explorer_outage_does_not_break_sweep():
    chain = Chain()
    chain.handler = lambda req: httpx.Response(500)  # type: ignore[method-assign]
    explorer = ExplorerClient("https://explorer.invalid", transport=httpx.MockTransport(chain.handler))
    prov = UsdtTronProvider(address=ADDR, contract=CONTRACT, explorer=explorer)
    with TestClient(create_app(make_settings(provider="off"), provider=prov,
                               deals=MockDealClient({"deal_1": DEAL}), clock=Clock())) as c:
        c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"}, headers=BUYER)
        out = c.post("/v1/payments/sweep", headers=ADMIN).json()
        assert {k: out[k] for k in ("expired", "polled", "updated")} == {"expired": 0, "polled": 1, "updated": 0}


def test_not_configured_and_wrong_currency():
    prov = UsdtTronProvider(address=None, contract=None, explorer=None)
    with TestClient(create_app(make_settings(provider="off"), provider=prov,
                               deals=MockDealClient({"deal_1": DEAL}), clock=Clock())) as c:
        r = c.post("/v1/invoices", json={"deal_id": "deal_1", "kind": "commission"}, headers=BUYER)
        assert r.status_code == 503 and r.json()["error"]["code"] == "provider_not_configured"
    app, _ = make(Chain())
    with TestClient(app) as c:
        body = {"deal_id": "d", "kind": "deal_payment", "payer_user_id": "u", "payee": "s",
                "amount": {"amount": "10.00", "currency": "EUR"}}
        r = c.post("/v1/invoices", json=body, headers=ADMIN)
        assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_currency"


def test_provider_selection_by_env_and_off_by_default_for_chain():
    from ff_payments.providers.mock import MockProvider
    from ff_payments.providers.registry import build_provider
    assert build_provider(make_settings(provider="off")) is None
    assert build_provider(make_settings(provider="bogus")) is None
    assert isinstance(build_provider(make_settings(provider="mock")), MockProvider)
    p = build_provider(make_settings(provider="usdt_tron", usdt_receive_address=ADDR, usdt_contract=CONTRACT,
                                     usdt_explorer_url="https://explorer.invalid"))
    assert isinstance(p, UsdtTronProvider) and p.address == ADDR
