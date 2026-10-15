# ruff: noqa: E501
"""QA round 3 edge cases: empty, duplicate, oversized, unicode."""

import pytest
from fastapi.testclient import TestClient

from ff_notifications.adapters.push import MockPushAdapter
from ff_notifications.clients.sourcing import MockSourcingClient
from ff_notifications.config import Settings
from ff_notifications.domain.models import ListingView, TrustBand
from ff_notifications.domain.money import Money
from ff_notifications.main import create_app


def H(user):
    return {"X-User-Id": user}


class Env:
    def __init__(self, c, mock):
        self.c, self.mock = c, mock

    def evaluate(self):
        r = self.c.post("/v1/alerts/evaluate", json={})
        assert r.status_code == 200, r.text
        return r.json()


@pytest.fixture
def env():
    m = Money.of("100", "USD")
    lst = ListingView(id="lst_1", kind="product", title="Pump", price_min=m, price_max=m, supplier_id="sup_1",
                      supplier_name="sup_1", category="pumps", condition="new", unit="piece", trust_band=TrustBand.GREEN)
    mock = MockSourcingClient([lst])
    app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"), sourcing=mock, push=MockPushAdapter())
    with TestClient(app) as c:
        yield Env(c, mock)


def test_empty_state_endpoints(env):
    assert env.c.get("/v1/alerts", headers=H("nobody")).json()["items"] == []
    assert env.c.get("/v1/devices", headers=H("nobody")).status_code == 200
    assert env.c.post("/v1/alerts/read-all", headers=H("nobody")).status_code in (200, 204)
    rep = env.evaluate()  # no watches at all
    assert rep["alerts_created"] == 0 and rep["alerts"] == []


def test_duplicate_search_watch_is_idempotent_and_unicode_query(env):
    body = {"search": {"q": "مضخة مياه 💧", "category": "pumps"}}
    a = env.c.post("/v1/watchlist", headers=H("u1"), json=body)
    b = env.c.post("/v1/watchlist", headers=H("u1"), json=body)
    assert a.status_code == 201 and b.status_code in (200, 201)
    assert env.c.get("/v1/watchlist", headers=H("u1")).json()["total"] == 1
    assert env.c.get("/v1/watchlist", headers=H("u1")).json()["items"][0]["search"]["q"] == "مضخة مياه 💧"


def test_oversized_fields_rejected(env):
    r = env.c.post("/v1/watchlist", headers=H("u1"), json={"search": {"q": "x" * 201}})
    assert r.status_code == 422
    r = env.c.post("/v1/watchlist", headers=H("u1"), json={"listing_id": "l" * 129})
    assert r.status_code == 422
    r = env.c.post("/v1/devices", headers=H("u1"), json={"token": "t" * 513, "platform": "android"})
    assert r.status_code == 422
    r = env.c.post("/v1/devices", headers=H("u1"), json={"token": "short", "platform": "android"})
    assert r.status_code == 422


@pytest.mark.parametrize("lid", ["lst 1", "lst/1", "مورد", "lst_1\n", "../x", "."])
def test_bad_listing_ids_rejected(env, lid):
    assert env.c.post("/v1/watchlist", headers=H("u1"), json={"listing_id": lid}).status_code == 422


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-5", "0", "1e999", "١٢٣", "", "abc", "9" * 40])
def test_hostile_target_price_never_500(env, amount):
    r = env.c.post("/v1/watchlist", headers=H("u1"), json={"listing_id": "lst_1", "target_price": {"amount": amount, "currency": "USD"}})
    assert r.status_code < 500, (amount, r.text)


@pytest.mark.parametrize("pct", ["NaN", "-1", "0", "101", "1e9", "abc"])
def test_hostile_drop_threshold_never_500(env, pct):
    r = env.c.post("/v1/watchlist", headers=H("u1"), json={"listing_id": "lst_1", "drop_threshold_pct": pct})
    assert r.status_code < 500, (pct, r.text)
    if r.status_code in (200, 201):
        env.mock.set_price("lst_1", "1")
        env.evaluate()  # evaluating with the stored threshold must not blow up


def test_hostile_user_ids_and_alert_ids(env):
    assert env.c.get("/v1/alerts", headers={"X-User-Id": "مستخدم".encode()}).status_code < 500
    assert env.c.post("/v1/alerts/alt_nope/read", headers=H("u1")).status_code == 404
    assert env.c.get("/v1/alerts", headers=H("u" * 5000)).status_code < 500


def test_tracking_events_empty_oversized_and_junk(env):
    assert env.c.post("/v1/internal/tracking-events", json={"events": []}).status_code == 422
    assert env.c.post("/v1/internal/tracking-events", json={"events": [{}] * 101}).status_code == 422
    r = env.c.post("/v1/internal/tracking-events", json={"events": [{}, {"user_id": 5}, {"reference": "ا" * 10000}]})
    assert r.status_code < 500, r.text


def test_prefs_unicode_and_quiet_hours_edges(env):
    for body in ({"quiet_hours": {"start": "25:99", "end": "00:00"}}, {"timezone": "Not/AZone"}, {"digest_email": "ا@ب.com"},
                 {"digest_email": "a" * 300 + "@x.com"}, {"channels": {"push": ["x"] * 9}}):
        assert env.c.put("/v1/notification-prefs", headers=H("u1"), json=body).status_code < 500, body
