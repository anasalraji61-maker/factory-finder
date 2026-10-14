from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ff_freight.config import Settings
from ff_freight.main import create_app

ADM = {"X-Admin-Token": "adm-secret", "X-User-Id": "admin"}


class Clock:
    """Deterministic clock: every reading advances 1 ms so ordering is total."""

    def __init__(self):
        self.t = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)

    def __call__(self):
        self.t += timedelta(milliseconds=1)
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


def uh(user="buyer1"):
    return {"X-User-Id": user}


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make_client(clock):
    clients = []

    def _make(**kw):
        kw.setdefault("database_url", "sqlite+aiosqlite:///:memory:")
        c = TestClient(create_app(Settings(**kw), clock=clock))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


NO_LIMITS = dict(
    rate_applications=0, rate_requests=0, rate_quotes=0, rate_ratings=0, rate_reports=0, admin_token="adm-secret"
)


@pytest.fixture
def client(make_client):
    return make_client(**NO_LIMITS)


APP = {
    "company_name": "Gulf Star Logistics",
    "country_code": "AE",
    "description": "Sea and air freight, China to Iraq",
    "lanes": [{"origin_country": "CN", "destination_country": "IQ"}, {"origin_country": "CN", "destination_country": "AE"}],
    "modes": ["sea", "air"],
    "incoterms": ["FOB", "CIF", "EXW"],
    "certifications": ["FIATA", "ISO 9001"],
}


def make_forwarder(client, user="fwd_user1", **over):
    """Apply + admin-approve; returns the forwarder id."""
    r = client.post("/v1/freight/applications", headers=uh(user), json={**APP, **over})
    assert r.status_code == 201, r.text
    a = client.post(f"/v1/admin/freight/applications/{r.json()['id']}/approve", headers=ADM)
    assert a.status_code == 200, a.text
    return a.json()["forwarder_id"]


def future(days=10):
    return (datetime(2026, 10, 15, tzinfo=UTC) + timedelta(days=days)).date().isoformat()


REQ = {
    "origin_country": "CN",
    "origin_place": "Shenzhen",
    "destination_country": "IQ",
    "destination_place": "Umm Qasr",
    "cargo_description": "Packaged ceramic tiles, palletised",
    "hs_code": "6907.21",
    "weight_kg": "18000",
    "volume_cbm": "28.5",
    "mode": "sea",
    "container_type": "40HC",
    "container_count": 1,
    "incoterm": "FOB",
    "ready_date": future(),
    "currency": "USD",
}


def make_request(client, user="buyer1", **over):
    r = client.post("/v1/freight/requests", headers=uh(user), json={**REQ, **over})
    assert r.status_code == 201, r.text
    return r.json()


QUOTE = {"amount": "2450.00", "currency": "USD", "transit_days": 28, "valid_days": 14,
         "inclusions": ["Ocean freight", "Origin THC"], "exclusions": ["Customs duties"], "terms": "Payment net 14 days"}  # fmt: skip


def make_quote(client, rid, user="fwd_user1", **over):
    r = client.post(f"/v1/freight/requests/{rid}/quotes", headers=uh(user), json={**QUOTE, **over})
    assert r.status_code == 201, r.text
    return r.json()
