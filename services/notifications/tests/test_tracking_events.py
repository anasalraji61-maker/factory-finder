"""Tracking outbox events -> inbox alerts + push (idempotent, prefs honored, internal token)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from ff_notifications.adapters.push import MockPush
from ff_notifications.clients.sourcing import MockSourcingClient
from ff_notifications.config import Settings
from ff_notifications.domain import tracking
from ff_notifications.domain.models import RuleKind
from ff_notifications.main import create_app

URL = "/v1/internal/tracking-events"
TOKEN = "tok-secret-0001"


def ev(key="trk:1:1", kind="status_changed", owner="u1", ship="shp_1", **payload):
    p = {
        "shipment_id": ship,
        "owner_id": owner,
        "reference": "MSKU1234567",
        "label": "Pumps order",
        "kind": kind,
        "status": "in_transit",
        "previous_status": "booked",
        "eta": "2026-11-02",
    }
    p.update(payload)
    return {
        "id": 1,
        "dedupe_key": key,
        "shipment_id": ship,
        "owner_id": owner,
        "kind": kind,
        "payload": p,
    }


class Env:
    def __init__(self, app, c, push):
        self.app, self.c, self.push, self.svc = app, c, push, app.state.service
        self.svc.clock = lambda: datetime(2026, 10, 13, 12, 0, tzinfo=UTC)

    async def post(self, *events, **kw):
        r = await self.c.post(URL, json={"events": list(events)}, **kw)
        assert r.status_code == 200, r.text
        return r.json()

    async def inbox(self, user="u1"):
        return (await self.c.get("/v1/alerts", headers={"X-User-Id": user})).json()

    async def device(self, user="u1"):
        r = await self.c.post(
            "/v1/devices",
            headers={"X-User-Id": user},
            json={"platform": "android", "token": "tok-device-1", "locale": "en"},
        )
        assert r.status_code in (200, 201)


def make(token=None):
    push = MockPush()
    s = Settings(database_url="sqlite+aiosqlite:///:memory:", internal_token=token)
    return create_app(s, sourcing=MockSourcingClient([]), push=push), push


@pytest.fixture
async def env():
    app, push = make()
    await app.state.service.store.create_all()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield Env(app, c, push)
    await app.state.service.store.dispose()


async def test_status_changed_creates_bilingual_alert_and_push(env):
    await env.device()
    rep = await env.post(ev())
    assert (
        rep["created"] == 1 and rep["pushes_sent"] == 1 and rep["results"][0]["status"] == "created"
    )
    (a,) = (await env.inbox())["items"]
    assert a["rule"] == "shipment_status" and a["watch_id"].startswith("shp_")
    assert "in transit" in a["body"] and "Pumps order" in a["body"] and "2026-11-02" in a["body"]
    assert "في الطريق" in a["body_ar"] and a["title_ar"] == "تحديث الشحنة"
    assert (
        a["payload"]["shipment"]["shipment_id"] == "shp_1"
        and a["payload"]["shipment"]["previous_status"] == "booked"
    )
    assert len(env.push.sent) == 1


async def test_delayed_event_text(env):
    rep = await env.post(
        ev(key="trk:1:2", kind="shipment_delayed", status="delayed", delayed=True, delay_hours=36.4)
    )
    assert rep["created"] == 1
    (a,) = (await env.inbox())["items"]
    assert (
        a["rule"] == "shipment_delayed"
        and "delayed by about 36 h" in a["body"]
        and "متأخرة بحدود 36 ساعة" in a["body_ar"]
    )


async def test_idempotent_by_dedupe_key_incl_in_batch(env):
    await env.device()
    first = await env.post(
        ev(), ev(key="trk:1:2", status="at_port"), ev()
    )  # same key twice in a batch
    assert (first["created"], first["duplicates"]) == (2, 1)
    again = await env.post(ev(), ev(key="trk:1:2", status="at_port"))
    assert (again["created"], again["duplicates"], again["pushes_sent"]) == (0, 2, 0)
    assert (await env.inbox())["total"] == 2
    assert len(env.push.sent) == 1  # one summary for the first batch; replay sends nothing


async def test_push_pref_honored_inbox_still_written(env):
    await env.device()
    r = await env.c.put(
        "/v1/notification-prefs",
        headers={"X-User-Id": "u1"},
        json={"channels": {"shipment_status": ["in_app"]}},
    )
    assert r.status_code == 200
    rep = await env.post(ev())
    assert rep["created"] == 1 and rep["pushes_sent"] == 0 and env.push.sent == []
    assert (await env.inbox())["total"] == 1
    # other kinds keep their own default channels
    rep = await env.post(ev(key="d1", kind="shipment_delayed", delay_hours=5))
    assert rep["pushes_sent"] == 1


async def test_events_are_per_owner(env):
    await env.post(ev(owner="u1"), ev(key="k2", owner="u2", ship="shp_2"))
    assert (await env.inbox("u1"))["total"] == 1 and (await env.inbox("u2"))["total"] == 1


async def test_invalid_events_reported_not_fatal(env):
    bad = [
        {"kind": "status_changed"},
        ev(key="k9", kind="nope"),
        {**ev(key="k8"), "owner_id": ""},
        {**ev(key="k7"), "payload": "x"},
    ]
    rep = await env.post(*bad, ev(key="ok"))
    assert (rep["created"], rep["invalid"]) == (1, 4)
    assert [r["status"] for r in rep["results"]].count("invalid") == 4
    assert (await env.c.post(URL, json={"events": []})).status_code == 422
    assert (await env.c.post(URL, json={"events": [ev()] * 101})).status_code == 422
    assert (await env.c.post(URL, json={"nope": 1})).status_code == 422


async def test_unknown_status_and_hostile_text_are_safe(env):
    rep = await env.post(ev(status="weird_code", label="x" * 500, eta=None))
    assert rep["created"] == 1
    (a,) = (await env.inbox())["items"]
    assert "weird code" in a["body"] and len(a["body"]) < 200


async def test_internal_token_required():
    app, _ = make(token="s3cret")
    await app.state.service.store.create_all()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        body = {"events": [ev()]}
        assert (await c.post(URL, json=body)).status_code == 401
        assert (
            await c.post(URL, json=body, headers={"X-Internal-Token": "wrong"})
        ).status_code == 401
        ok = await c.post(URL, json=body, headers={"X-Internal-Token": "s3cret"})
        assert ok.status_code == 200 and ok.json()["created"] == 1
    await app.state.service.store.dispose()


def test_parse_and_rules():
    assert tracking.parse_event(ev()).rule is RuleKind.SHIPMENT_STATUS
    assert tracking.parse_event(ev(kind="shipment_delayed")).rule is RuleKind.SHIPMENT_DELAYED
    assert len(tracking.parse_event(ev(ship="s" * 100)).watch_id) <= 40
    assert tracking.status_texts("delivered") == ("delivered", "تم التسليم")


def test_non_finite_delay_hours_never_crash_build():
    for bad in (float("inf"), float("nan"), 1e308):
        e = tracking.parse_event(ev(kind="shipment_delayed", delay_hours=bad))
        msg, payload = tracking.build(e)
        assert "delayed" in msg.body
        if bad != 1e308:
            assert "delay_hours" not in payload.shipment


def test_every_tracking_status_has_arabic_text():
    # tracking's ShipmentStatus vocabulary (contracts/openapi/tracking.yaml); no cross-module import
    statuses = [
        "booked", "gate_in", "loaded", "departed", "in_transit", "transshipment", "arrived",
        "discharged", "customs_hold", "released", "out_for_delivery", "delivered", "exception",
    ]
    for s in statuses:
        en, ar = tracking.status_texts(s)
        assert ar != en and any("؀" <= ch <= "ۿ" for ch in ar), s
