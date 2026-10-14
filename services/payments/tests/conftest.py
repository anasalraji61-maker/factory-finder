import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ff_payments import webhooks
from ff_payments.clients.deals import MockDealClient
from ff_payments.config import Settings
from ff_payments.main import create_app
from ff_payments.providers.mock import MockProvider

BUYER = {"X-User-Id": "buyer1"}
SUPPLIER = {"X-User-Id": "sup1"}
OTHER = {"X-User-Id": "mallory"}
ADMIN = {"X-Admin-Token": "admin-secret-test"}
WH_SECRET = "whsec-test"

DEAL = {
    "id": "deal_1", "buyer_id": "buyer1", "supplier_user_id": "sup1", "kind": "product",
    "subtotal": {"amount": "12500.00", "currency": "USD"},
    "commission": {"rate": "0.03", "amount": {"amount": "375.00", "currency": "USD"}, "min_fee_applied": False},
}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


def make_settings(**over) -> Settings:
    base = {"database_url": "sqlite+aiosqlite:///:memory:", "deal_client": "mock", "provider": "mock",
            "admin_token": "admin-secret-test", "webhook_secret_mock": WH_SECRET}
    return Settings(**{**base, **over})


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
def client(clock, provider):
    deals = MockDealClient({"deal_1": DEAL})
    with TestClient(create_app(make_settings(), provider=provider, deals=deals, clock=clock)) as c:
        c.provider, c.clock, c.deals = provider, clock, deals
        yield c


def mk(client, kind="commission", headers=BUYER, deal_id="deal_1", **over):
    return client.post("/v1/invoices", json={"deal_id": deal_id, "kind": kind, **over}, headers=headers)


def post_event(client, body: dict, *, secret=WH_SECRET, ts=None, provider="mock", sig=None):
    raw = json.dumps(body).encode()
    ts = ts if ts is not None else int(client.clock().timestamp())
    headers = {"X-FF-Signature": sig if sig is not None else webhooks.sign(secret, raw, ts),
               "Content-Type": "application/json"}
    return client.post(f"/v1/payments/webhooks/{provider}", content=raw, headers=headers)
