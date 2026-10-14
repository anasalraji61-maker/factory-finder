"""Outbox relay: mock client only, no network."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx

from ff_tracking.config import Settings
from ff_tracking.main import create_app
from ff_tracking.relay import (
    HttpNotifyClient,
    MockNotifyClient,
    NotifyUnavailable,
    OutboxRelay,
    build_relay,
)
from ff_tracking.repository import ShipmentRepository, make_engine

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def setup(n=3, **kw):
    repo = ShipmentRepository(make_engine("sqlite+aiosqlite:///:memory:"))
    clock, client = Clock(), kw.pop("client", None) or MockNotifyClient()

    async def seed():
        await repo.create_tables()
        for i in range(n):
            await repo.add_outbox(dedupe_key=f"k{i}", shipment_id="shp_1", owner_id="u1", kind="status_changed",
                                  payload=json.dumps({"status": "in_transit", "i": i}), created_at=T0)
    return repo, clock, client, seed


def run(coro):
    return asyncio.run(coro)


def test_delivers_in_order_and_marks_delivered():
    async def go():
        repo, clock, client, seed = setup()
        await seed()
        relay = OutboxRelay(repo, client, clock)
        assert (await relay.run_once())["delivered"] == 3
        assert [e["dedupe_key"] for e in client.calls[0]] == ["k0", "k1", "k2"]
        assert client.calls[0][0]["payload"]["i"] == 0 and set(client.calls[0][0]) == {
            "id", "dedupe_key", "shipment_id", "owner_id", "kind", "payload"}
        assert await repo.pending_outbox() == []
        assert (await relay.run_once())["sent"] == 0
        assert (await repo.outbox_stats())["delivered"] == 3
    run(go())


def test_duplicate_counts_as_delivered_and_batching():
    async def go():
        repo, clock, client, seed = setup(5)
        client.seen.add("k1")
        await seed()
        relay = OutboxRelay(repo, client, clock, batch_size=2)
        assert (await relay.run_once())["delivered"] == 2
        assert (await relay.run_once())["delivered"] == 2
        assert (await relay.run_once())["delivered"] == 1
        assert len(client.calls) == 3
    run(go())


def test_invalid_item_goes_dead_others_delivered():
    async def go():
        repo, clock, client, seed = setup(client=MockNotifyClient(invalid_keys={"k1"}))
        await seed()
        relay = OutboxRelay(repo, client, clock)
        st = await relay.run_once()
        assert st["delivered"] == 2 and st["invalid"] == 1
        stats = await repo.outbox_stats()
        assert stats["dead"] == 1 and stats["pending"] == 0
        assert (await relay.run_once())["sent"] == 0
    run(go())


def test_backoff_then_dead_and_recovery():
    async def go():
        repo, clock, client, seed = setup(1, client=MockNotifyClient(fail=True))
        await seed()
        relay = OutboxRelay(repo, client, clock, max_attempts=3, backoff_base=10, backoff_max=15)
        assert (await relay.run_once())["retried"] == 1
        assert (await relay.run_once())["sent"] == 0  # still backing off
        clock.now += timedelta(seconds=10)
        assert (await relay.run_once())["retried"] == 1
        clock.now += timedelta(seconds=15)  # capped (20 -> 15)
        assert (await relay.run_once())["dead"] == 1
        clock.now += timedelta(days=1)
        assert (await relay.run_once())["sent"] == 0
        assert (await repo.outbox_stats())["dead"] == 1
    run(go())


def test_recovers_after_outage():
    async def go():
        repo, clock, client, seed = setup(2, client=MockNotifyClient(fail=True))
        await seed()
        relay = OutboxRelay(repo, client, clock, backoff_base=10)
        await relay.run_once()
        stats = await repo.outbox_stats()
        assert stats["retrying"] == 2
        client.fail = False
        clock.now += timedelta(seconds=10)
        assert (await relay.run_once())["delivered"] == 2
    run(go())


def test_http_client_shapes_and_errors():
    seen = {}

    def handler(req: httpx.Request):
        seen["token"], seen["body"], seen["path"] = req.headers.get("X-Internal-Token"), json.loads(req.content), req.url.path
        if seen["body"]["events"][0]["dedupe_key"] == "boom":
            return httpx.Response(503)
        return httpx.Response(200, json={"results": [{"index": 0, "dedupe_key": "a", "status": "created"}]})

    c = HttpNotifyClient("http://n.local/", "tok", transport=httpx.MockTransport(handler))

    async def go():
        res = await c.send([{"dedupe_key": "a"}])
        assert res[0].status == "created" and seen["token"] == "tok" and seen["path"] == "/v1/internal/tracking-events"
        try:
            await c.send([{"dedupe_key": "boom"}])
        except NotifyUnavailable as e:
            assert "503" in str(e)
        else:
            raise AssertionError
    run(go())


def test_off_by_default_and_status_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    s = Settings(database_url="sqlite+aiosqlite:///:memory:")
    assert build_relay(s, None, Clock()) is None
    assert build_relay(Settings(notify_relay="on"), None, Clock()) is None  # no base URL
    mock = MockNotifyClient()
    app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:", notify_relay="on", notify_poll_seconds=3600),
                     notify_client=mock)
    with TestClient(app) as c:
        body = c.get("/v1/internal/outbox-status").json()
        assert body["relay"] == "on" and body["pending"] == 0
    with TestClient(create_app(s)) as c:
        assert c.get("/v1/internal/outbox-status").json()["relay"] == "off"
