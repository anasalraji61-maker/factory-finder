from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ff_notifications.adapters.push import FcmPushAdapter, MockPushAdapter
from ff_notifications.clients.sourcing import MockSourcingClient
from ff_notifications.config import Settings
from ff_notifications.domain.models import ListingView, TrustBand
from ff_notifications.domain.money import Money
from ff_notifications.main import create_app


def H(user):
    return {"X-User-Id": user}


def listing(lid="lst_1", price="100", supplier="sup_1", category="pumps", trust=TrustBand.GREEN):
    m = Money.of(price, "USD")
    return ListingView(
        id=lid,
        kind="product",
        title=f"Pump {lid}",
        price_min=m,
        price_max=m,
        supplier_id=supplier,
        supplier_name=supplier,
        category=category,
        condition="new",
        unit="piece",
        trust_band=trust,
    )


class Env:
    def __init__(self, client, mock, push, svc):
        self.c, self.mock, self.push, self.svc = client, mock, push, svc
        self.now = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
        svc.clock = lambda: self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)

    def watch(self, user="u1", lid="lst_1", **extra):
        r = self.c.post("/v1/watchlist", headers=H(user), json={"listing_id": lid, **extra})
        assert r.status_code in (200, 201), r.text
        return r.json()

    def evaluate(self, **body):
        r = self.c.post("/v1/alerts/evaluate", json=body)
        assert r.status_code == 200, r.text
        return r.json()

    def rules(self, report):
        return sorted(a["rule"] for a in report["alerts"])


@pytest.fixture
def env():
    mock = MockSourcingClient([listing()])
    push = MockPushAdapter()
    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:"), sourcing=mock, push=push
    )
    with TestClient(app) as c:
        yield Env(c, mock, push, app.state.service)


def test_health(env):
    assert env.c.get("/health").json()["service"] == "notifications"


def test_watchlist_crud_idempotent_and_ownership(env):
    w = env.watch(target_price={"amount": "80", "currency": "USD"})
    assert w["type"] == "listing" and w["target_price"] == {"amount": "80", "currency": "USD"}
    again = env.c.post("/v1/watchlist", headers=H("u1"), json={"listing_id": "lst_1"})
    assert again.status_code == 200 and again.json()["id"] == w["id"]
    s = env.c.post(
        "/v1/watchlist", headers=H("u1"), json={"search": {"q": "pump", "category": "pumps"}}
    )
    assert s.status_code == 201 and s.json()["type"] == "search"
    assert env.c.get("/v1/watchlist", headers=H("u1")).json()["total"] == 2
    assert env.c.get("/v1/watchlist", headers=H("u2")).json()["total"] == 0
    assert env.c.get("/v1/watchlist").status_code == 401
    assert env.c.delete(f"/v1/watchlist/{w['id']}", headers=H("u2")).status_code == 403
    assert env.c.delete("/v1/watchlist/wch_x", headers=H("u1")).status_code == 404
    assert env.c.delete(f"/v1/watchlist/{w['id']}", headers=H("u1")).status_code == 204
    bad = env.c.post("/v1/watchlist", headers=H("u1"), json={})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_watch"
    both = env.c.post("/v1/watchlist", headers=H("u1"), json={"listing_id": "a", "search": {}})
    assert both.status_code == 422


def test_price_drop_rule_and_no_repeat(env):
    env.watch()
    assert env.evaluate()["alerts_created"] == 0  # first check only sets the baseline
    env.mock.set_price("lst_1", "96")  # 4% < 5% threshold
    assert env.evaluate()["alerts_created"] == 0
    env.mock.set_price("lst_1", "90")
    rep = env.evaluate()
    assert env.rules(rep) == ["price_drop"]
    assert rep["alerts"][0]["payload"]["drop_pct"] == "10.00"
    assert env.evaluate()["alerts_created"] == 0  # same price: nothing new


def test_below_target_rule_and_rearm(env):
    env.watch(target_price={"amount": "80", "currency": "USD"})
    env.evaluate()
    env.mock.set_price("lst_1", "79")
    assert env.rules(env.evaluate()) == ["below_target"]
    assert env.evaluate()["alerts_created"] == 0  # already told
    env.mock.set_price("lst_1", "120")  # above target again: re-arms
    env.evaluate()
    env.advance(hours=25)
    env.mock.set_price("lst_1", "70")
    assert "below_target" in env.rules(env.evaluate())


def test_cheaper_equivalent_rule(env):
    env.mock.put(listing("lst_2", "60", supplier="sup_2"))
    env.mock.put(listing("lst_3", "50", supplier="sup_3", trust=TrustBand.RED))  # ignored: red
    env.mock.put(listing("lst_4", "40", supplier="sup_4", category="valves"))  # other category
    env.watch()
    rep = env.evaluate()
    assert env.rules(rep) == ["cheaper_equivalent"]
    assert rep["alerts"][0]["payload"]["listing_ids"] == ["lst_1", "lst_2"]
    assert env.evaluate()["alerts_created"] == 0


def test_back_in_stock_and_delisted(env):
    env.watch()
    env.evaluate()
    env.mock.remove("lst_1")
    assert env.evaluate()["alerts_created"] == 0
    env.mock.put(listing())
    assert env.rules(env.evaluate()) == ["back_in_stock"]


def test_cooldown_defers_then_releases(env):
    env.watch()
    env.evaluate()
    env.mock.set_price("lst_1", "90")
    assert env.rules(env.evaluate()) == ["price_drop"]
    env.mock.set_price("lst_1", "80")
    rep = env.evaluate()
    assert rep["alerts_created"] == 0
    assert rep["skipped"] == [
        {"watch_id": rep["skipped"][0]["watch_id"], "rule": "price_drop", "reason": "cooldown"}
    ]
    env.advance(hours=25)  # event stayed pending, so it is reported once the cooldown is over
    assert env.rules(env.evaluate()) == ["price_drop"]


def test_saved_search_new_results(env):
    env.c.post("/v1/watchlist", headers=H("u1"), json={"search": {"category": "pumps"}})
    assert env.evaluate()["alerts_created"] == 0  # first snapshot
    env.mock.put(listing("lst_9", "100", supplier="sup_9"))
    rep = env.evaluate()
    assert env.rules(rep) == ["new_results"]
    assert rep["alerts"][0]["payload"]["listing_ids"] == ["lst_9"]


def test_inbox_and_ownership(env):
    env.watch()
    env.watch(user="u2")
    env.evaluate()
    env.mock.set_price("lst_1", "50")
    rep = env.evaluate()
    assert rep["alerts_created"] == 2
    inbox = env.c.get("/v1/alerts", headers=H("u1")).json()
    assert inbox["total"] == 1 and inbox["unread_total"] == 1
    a = inbox["items"][0]
    assert a["title"] and a["title_ar"] and not a["read"]
    assert env.c.post(f"/v1/alerts/{a['id']}/read", headers=H("u2")).status_code == 403
    assert env.c.post("/v1/alerts/alt_nope/read", headers=H("u1")).status_code == 404
    done = env.c.post(f"/v1/alerts/{a['id']}/read", headers=H("u1")).json()
    assert done["read"] and done["read_at"]
    assert env.c.get("/v1/alerts?unread_only=true", headers=H("u1")).json()["total"] == 0
    assert env.c.get("/v1/alerts?unread_only=true", headers=H("u2")).json()["total"] == 1
    assert env.c.post("/v1/alerts/read-all", headers=H("u2")).json() == {"marked": 1}
    assert env.c.get("/v1/alerts", headers=H("u1")).json()["items"][0]["id"] == a["id"]


def test_devices_and_push(env):
    r = env.c.post(
        "/v1/devices",
        headers=H("u1"),
        json={"platform": "android", "token": "tok-12345678", "locale": "ar"},
    )
    assert r.status_code == 201
    again = env.c.post(
        "/v1/devices",
        headers=H("u1"),
        json={"platform": "android", "token": "tok-12345678", "locale": "en"},
    )
    assert (
        again.status_code == 200
        and again.json()["id"] == r.json()["id"]
        and again.json()["locale"] == "en"
    )
    assert len(env.c.get("/v1/devices", headers=H("u1")).json()["items"]) == 1
    env.watch()
    env.evaluate()
    env.mock.set_price("lst_1", "50")
    rep = env.evaluate()
    assert rep["pushes_sent"] == 1 and len(env.push.sent) == 1
    assert env.push.sent[0]["title"].startswith("You have")  # device locale en
    assert env.c.delete(f"/v1/devices/{r.json()['id']}", headers=H("u2")).status_code == 403
    assert env.c.delete(f"/v1/devices/{r.json()['id']}", headers=H("u1")).status_code == 204
    assert (
        env.c.post(
            "/v1/devices", headers=H("u1"), json={"platform": "web", "token": "tok-12345678"}
        ).status_code
        == 422
    )


def test_sourcing_failure_is_reported_not_raised(env):
    env.watch()
    env.mock.fail = True
    rep = env.evaluate()
    assert rep["evaluated"] == 0 and len(rep["errors"]) == 1


def test_evaluate_requires_internal_token():
    s = Settings(database_url="sqlite+aiosqlite:///:memory:", internal_token="secret")
    with TestClient(create_app(s, sourcing=MockSourcingClient(), push=MockPushAdapter())) as c:
        assert c.post("/v1/alerts/evaluate").status_code == 401
        assert (
            c.post("/v1/alerts/evaluate", headers={"X-Internal-Token": "secret"}).status_code == 200
        )
        assert c.get("/v1/alerts", headers=H("u1")).status_code == 401


async def test_fcm_stub_disabled_by_default():
    from ff_notifications.domain.models import Device, Locale, Platform

    now = datetime.now(UTC)
    dev = Device("d", "u", Platform.ANDROID, Locale.EN, "t", now, now)
    res = await FcmPushAdapter().send(dev, "a", "b", {})
    assert not res.sent and res.reason == "fcm_disabled"
