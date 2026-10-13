from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ff_rfq.config import Settings
from ff_rfq.main import create_app

BUYER = {"X-User-Id": "buyer1"}
SUP_A = {"X-User-Id": "supA"}
SUP_B = {"X-User-Id": "supB"}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client(clock):
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:", sourcing_client="mock")
    with TestClient(create_app(settings, clock=clock)) as c:
        yield c


def new_request(client, **over):
    body = {"kind": "product", "title": "LED panel lights", "quantity": "1000", "unit": "piece",
            "destination": {"country_code": "IQ", "city": "Baghdad"}, **over}
    r = client.post("/v1/requests", json=body, headers=BUYER)
    assert r.status_code == 201, r.text
    return r.json()


def new_offer(client, request_id, headers=SUP_A, amount="12.50", currency="USD", **over):
    body = {"price": {"amount": amount, "currency": currency}, "supplier_name": "Acme Ltd", **over}
    r = client.post(f"/v1/requests/{request_id}/offers", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()
