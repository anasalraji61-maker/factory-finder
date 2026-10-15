"""security-review-2026-10-g: caps, retention, provider input validation, no delivered regression."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import H
from fastapi.testclient import TestClient

from ff_tracking.adapters.base import ProviderUnavailable
from ff_tracking.adapters.http import (
    HttpAwbProvider,
    HttpContainerProvider,
    HttpVesselPositionProvider,
)
from ff_tracking.config import Settings
from ff_tracking.domain.enums import ReferenceType
from ff_tracking.domain.normalize import MAX_EVENTS, normalize_events
from ff_tracking.main import create_app
from ff_tracking.relay import MockNotifyClient, OutboxRelay
from ff_tracking.repository import ShipmentRepository, make_engine

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def test_per_user_shipment_cap(clock):
    s = Settings(database_url="sqlite+aiosqlite:///:memory:", max_shipments_per_user=1)
    with TestClient(create_app(s, clock=clock)) as c:
        assert c.post("/v1/shipments", json={"reference": "CSQU3054383", "reference_type": "container"}, headers=H).status_code == 201
        r = c.post("/v1/shipments", json={"reference": "176-12345675", "reference_type": "awb"}, headers=H)
        assert r.status_code == 409 and r.json()["error"]["code"] == "shipment_limit_reached"
        other = c.post("/v1/shipments", json={"reference": "176-12345675", "reference_type": "awb"}, headers={"X-User-Id": "usr_b"})
        assert other.status_code == 201


def test_validate_path_length_capped(client):
    assert client.get("/v1/validate/container/" + "A" * 65).status_code == 422


@pytest.mark.parametrize("cls,kw", [
    (HttpContainerProvider, dict(ref="../../admin", rtype=ReferenceType.CONTAINER)),
    (HttpContainerProvider, dict(ref="MSKU1234?x=1", rtype=ReferenceType.BL)),
    (HttpAwbProvider, dict(ref="176-1234567/../x", rtype=ReferenceType.AWB)),
])
def test_providers_reject_malformed_reference_without_network(cls, kw):
    calls = []

    def h(req):
        calls.append(req)
        return httpx.Response(200, json={})

    p = cls("https://api.example.test", "k", client=httpx.AsyncClient(transport=httpx.MockTransport(h)), env={})
    with pytest.raises(ProviderUnavailable) as e:
        asyncio.run(p.track(kw["ref"], kw["rtype"], None, anchor=NOW, now=NOW))
    assert e.value.reason == "unsupported" and not calls
    v = HttpVesselPositionProvider("https://api.example.test", "k", client=httpx.AsyncClient(transport=httpx.MockTransport(h)), env={})
    with pytest.raises(ProviderUnavailable):
        asyncio.run(v.vessel_eta("12/../3", now=NOW))
    assert not calls


def test_events_and_descriptions_are_bounded():
    raw = [{"code": "GATE_IN", "timestamp": (NOW - timedelta(days=400, minutes=i)).isoformat(), "actual": True,
            "description": "x" * 5000, "hub": f"H{i}"} for i in range(MAX_EVENTS + 50)]
    ev, *_ = normalize_events(raw, source="t", now=NOW)
    assert len(ev) <= MAX_EVENTS and all(len(e.description) <= 300 for e in ev)


def test_outbox_retention_purges_only_settled_rows():
    repo = ShipmentRepository(make_engine("sqlite+aiosqlite:///:memory:"))
    old = NOW - timedelta(days=60)

    async def run():
        await repo.create_tables()
        for k in ("a", "b", "c"):
            await repo.add_outbox(dedupe_key=k, shipment_id="s", owner_id="u", kind="status_changed",
                                  payload=json.dumps({}), created_at=old)
        await repo.record_outbox_result(1, delivered_at=old)
        await repo.record_outbox_result(2, error="x", dead_at=old)
        relay = OutboxRelay(repo, MockNotifyClient(), lambda: NOW, retention_days=30)
        await relay.run_once()
        st = await repo.outbox_stats()
        return st

    st = asyncio.run(run())
    # rows 1 (delivered) and 2 (dead) were purged; row 3 was pending, so it was kept and then delivered
    assert st == {**st, "delivered": 1, "dead": 0, "pending": 0}


def test_delivered_shipment_is_not_reopened_by_a_stale_snapshot():
    from ff_tracking.domain.enums import ShipmentStatus as S
    from ff_tracking.domain.models import Shipment, TrackingEvent, TrackingSnapshot

    def ev(status, h):
        return TrackingEvent(id=f"e{h}", status=status, description="d", description_ar="d",
                             timestamp=NOW - timedelta(hours=h), source="t")

    sh = Shipment(id="shp_1", owner_id="u", reference="CSQU3054383", reference_type=ReferenceType.CONTAINER,
                  created_at=NOW, updated_at=NOW)
    sh.apply_snapshot(TrackingSnapshot(provider="t", fetched_at=NOW, events=(ev(S.IN_TRANSIT, 5), ev(S.DELIVERED, 1))), NOW)
    assert sh.status == S.DELIVERED
    sh.apply_snapshot(TrackingSnapshot(provider="t", fetched_at=NOW, events=(ev(S.IN_TRANSIT, 5),)), NOW)
    assert sh.status == S.DELIVERED and len(sh.events) == 2
