"""Real-provider skeletons, normalization, fallback, kill switch, throttle, refresh job and outbox.

No network: every HTTP call goes through ``httpx.MockTransport`` with recorded JSON fixtures.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from conftest import Clock, H
from fastapi.testclient import TestClient

from ff_tracking.adapters.base import ProviderUnavailable
from ff_tracking.adapters.http import (
    HttpAwbProvider,
    HttpContainerProvider,
    HttpVesselPositionProvider,
)
from ff_tracking.adapters.mock import MockProvider
from ff_tracking.adapters.router import FallbackProvider, RoutingProvider
from ff_tracking.config import Settings
from ff_tracking.domain.carriers import (
    AIRLINES,
    OCEAN_CARRIERS,
    carrier_for_awb_prefix,
    carrier_for_container_owner,
)
from ff_tracking.domain.enums import ReferenceType
from ff_tracking.domain.enums import ShipmentStatus as S
from ff_tracking.domain.eta import assess_eta
from ff_tracking.domain.normalize import normalize_events, parse_ts, resolve_location
from ff_tracking.domain.validators import container_check_digit, validate_awb
from ff_tracking.jobs import RefreshJob
from ff_tracking.main import create_app

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def fx(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def container_no(prefix4: str = "MSKU", serial: str = "000000") -> str:
    ten = prefix4 + serial
    return ten + str(container_check_digit(ten))


class FakeTime:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    async def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def make(cls, handler, *, env=None, ft=None, key="k", **kw):
    ft = ft or FakeTime()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = cls("https://api.example.test", key, client=client, env=env if env is not None else {},
            clock=ft, sleep=ft.sleep, **kw)
    return p, ft


def json_handler(payload, calls=None):
    def h(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(200, json=payload)
    return h


async def track(p, ref=None, rtype=ReferenceType.CONTAINER, carrier=None, now=NOW):
    return await p.track(ref or container_no(), rtype, carrier, anchor=now, now=now)


# ---------------- carrier detection ----------------

def test_tables_are_big_and_unique():
    assert len(OCEAN_CARRIERS) >= 20 and len(AIRLINES) >= 40
    assert len({c.scac for c in OCEAN_CARRIERS}) == len(OCEAN_CARRIERS)
    assert len({c.awb_prefix for c in AIRLINES}) == len(AIRLINES)


def test_carrier_detection_container_and_awb():
    assert carrier_for_container_owner("MSKU").scac == "MAEU"
    assert carrier_for_container_owner("HDMU").code == "hmm"
    assert carrier_for_awb_prefix("176").iata_code == "EK"
    assert carrier_for_awb_prefix("023").code == "fedex"
    assert HttpContainerProvider.detect_scac(container_no(), ReferenceType.CONTAINER, None) == "MAEU"
    assert HttpContainerProvider.detect_scac("ZIMU12345678", ReferenceType.BL, None) == "ZIMU"
    assert HttpContainerProvider.detect_scac(container_no("ABCU"), ReferenceType.CONTAINER, None) is None


async def test_container_request_carries_scac_ua_and_key():
    calls: list[httpx.Request] = []
    p, _ = make(HttpContainerProvider, json_handler(fx("container_ok.json"), calls))
    await track(p)
    r = calls[0]
    assert r.url.path == f"/v1/containers/{container_no()}" and r.url.params["carrier"] == "MAEU"
    assert r.headers["user-agent"].startswith("FactoryFinderBot/") and r.headers["authorization"] == "Bearer k"
    assert "k" not in repr(p).replace("configured", "")  # repr never shows the key


async def test_bl_without_carrier_is_unsupported():
    p, _ = make(HttpContainerProvider, json_handler(fx("container_ok.json")))
    with pytest.raises(ProviderUnavailable) as e:
        await p.track("XXXX12345678", ReferenceType.BL, None, anchor=NOW, now=NOW)
    assert e.value.reason == "unsupported"


# ---------------- normalization ----------------

async def test_container_normalization_order_dedupe_milestones():
    p, _ = make(HttpContainerProvider, json_handler(fx("container_ok.json")))
    snap = await track(p)
    statuses = [e.status for e in snap.events]
    # gate_in (deduped), loaded, departed, then Port Klang discharge/load = transshipment
    assert statuses == [S.GATE_IN, S.LOADED, S.DEPARTED, S.TRANSSHIPMENT, S.LOADED]
    assert [e.timestamp for e in snap.events] == sorted(e.timestamp for e in snap.events)
    assert all(e.timestamp.tzinfo is not None and e.timestamp.utcoffset() == timedelta(0) for e in snap.events)
    assert snap.events[0].timestamp == datetime(2026, 9, 5, 0, 0, tzinfo=UTC)  # +08:00 -> UTC
    assert snap.events[0].location.hub_id == "CNSHA" and snap.events[0].location.country_code == "CN"
    assert snap.events[3].location.hub_id == "MYPKG"
    assert set(snap.milestones) == {"gate_in", "loaded", "departed", "transshipment"}
    assert snap.eta == datetime(2026, 10, 20, 6, 0, tzinfo=UTC)  # planned arrival is the ETA, not an event
    assert snap.destination_hub_id == "IQUQR" and snap.destination.country_code == "IQ"
    assert snap.carrier.code == "maersk" and snap.vessel.imo == "9074729"
    assert all(e.description_ar for e in snap.events)


async def test_arrived_discharged_gate_out_milestones():
    p, _ = make(HttpContainerProvider, json_handler(fx("container_arrived.json")))
    snap = await track(p)
    assert [e.status for e in snap.events] == [S.DEPARTED, S.ARRIVED, S.OUT_FOR_DELIVERY]
    assert set(snap.milestones) == {"departed", "arrived", "gate_out"}


def test_normalize_helpers():
    raw = [{"code": "mystery", "timestamp": "2026-09-01T00:00:00Z"},
           {"code": "DELIVERED", "timestamp": "garbage"},
           {"code": "delivered", "timestamp": 1790000000, "hub": "XXABC", "name": "Somewhere"},
           {"code": "BKD", "timestamp": "2026-09-01T00:00:00", "hub": "PVG"}]
    events, eta, ms, skipped = normalize_events(raw, source="t", now=datetime(2027, 1, 1, tzinfo=UTC))
    assert skipped == 2 and [e.status for e in events] == [S.BOOKED, S.DELIVERED] and eta is None
    assert events[1].location.hub_id == "XXABC" and events[1].location.country_code == "XX"
    assert events[0].location.hub_id == "PVG" and "delivered" in ms
    assert parse_ts("2026-09-01T00:00:00") == datetime(2026, 9, 1, tzinfo=UTC)
    assert resolve_location(None, None) is None


def test_future_dated_actual_event_is_not_in_timeline():
    ev, eta, _, _ = normalize_events(
        [{"code": "ARRIVAL", "timestamp": "2026-12-01T00:00:00Z", "hub": "IQUQR"}], source="t", now=NOW)
    assert ev == [] and eta == datetime(2026, 12, 1, tzinfo=UTC)


async def test_awb_normalization():
    p, _ = make(HttpAwbProvider, json_handler(fx("awb_ok.json")))
    ref = validate_awb("176-12345675").normalized
    snap = await p.track(ref, ReferenceType.AWB, None, anchor=NOW, now=NOW)
    assert [e.status for e in snap.events] == [S.GATE_IN, S.LOADED, S.DEPARTED, S.TRANSSHIPMENT]
    assert snap.flight.number == "EK306" and snap.carrier.code == "emirates"
    assert snap.origin_hub_id == "PVG" and snap.destination.country_code == "IQ"
    assert snap.eta == datetime(2026, 10, 3, 14, tzinfo=UTC)
    assert snap.events[-1].location.hub_id == "DXB"  # arrival at a non-destination hub = transshipment


async def test_vessel_position_eta_only():
    p, _ = make(HttpVesselPositionProvider, json_handler(fx("vessel_ok.json")))
    v = await p.vessel_eta("9074729", now=NOW)
    assert v.eta == datetime(2026, 10, 18, tzinfo=UTC) and v.destination_locode == "IQUQR"
    assert v.point.lat == 12.5 and v.speed_knots == 17.2


async def test_router_adds_vessel_eta_when_missing_and_survives_its_failure():
    payload = fx("container_delayed.json")
    payload["data"].pop("eta")
    payload["data"]["vessel"] = {"name": "MSC Aurora", "imo": "9074729"}
    cont, _ = make(HttpContainerProvider, json_handler(payload))
    ves, _ = make(HttpVesselPositionProvider, json_handler(fx("vessel_ok.json")))
    snap = await RoutingProvider(container=cont, vessel=ves).track(
        container_no(), ReferenceType.CONTAINER, None, anchor=NOW, now=NOW)
    assert snap.eta == datetime(2026, 10, 18, tzinfo=UTC)
    bad, _ = make(HttpVesselPositionProvider, lambda r: httpx.Response(500))
    snap = await RoutingProvider(container=cont, vessel=bad).track(
        container_no(), ReferenceType.CONTAINER, None, anchor=NOW, now=NOW)
    assert snap.eta is None and snap.events
    only = await RoutingProvider(vessel=ves).track("9074729", ReferenceType.VESSEL_IMO, None, anchor=NOW, now=NOW)
    assert only.status is S.IN_TRANSIT and only.eta and only.events[0].location.point.lat == 12.5


# ---------------- ETA / delay ----------------

def test_delay_flag_and_stale_eta_recompute():
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    assert assess_eta(t0, None, S.IN_TRANSIT, t0 - timedelta(days=5)) == (t0, t0, False, None)
    eta, init, delayed, hours = assess_eta(t0 + timedelta(days=3), t0, S.IN_TRANSIT, t0)
    assert delayed and hours == 72 and init == t0
    assert assess_eta(t0 + timedelta(hours=6), t0, S.IN_TRANSIT, t0)[2] is False  # within tolerance
    eta, init, delayed, hours = assess_eta(t0, t0, S.IN_TRANSIT, t0 + timedelta(days=2))
    assert delayed and eta == t0 + timedelta(days=3) and hours == 48  # stale -> now + 24 h
    assert assess_eta(t0, t0, S.ARRIVED, t0 + timedelta(days=2))[2] is False  # landed: not stale
    assert assess_eta(None, None, S.BOOKED, t0) == (None, None, False, None)


# ---------------- failures, kill switch, throttle ----------------

@pytest.mark.parametrize("status,reason", [(500, "upstream_error"), (503, "upstream_error"), (429, "rate_limited"),
                                           (401, "blocked"), (403, "blocked")])
async def test_http_failures_raise_with_reason(status, reason):
    p, _ = make(HttpContainerProvider, lambda r: httpx.Response(status))
    with pytest.raises(ProviderUnavailable) as e:
        await track(p)
    assert e.value.reason == reason


async def test_timeout_bad_json_and_bad_shape():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    p, _ = make(HttpContainerProvider, boom)
    with pytest.raises(ProviderUnavailable) as e:
        await track(p)
    assert e.value.reason == "timeout"
    p, _ = make(HttpContainerProvider, lambda r: httpx.Response(200, content=b"<html>"))
    with pytest.raises(ProviderUnavailable) as e:
        await track(p)
    assert e.value.reason == "bad_payload"
    p, _ = make(HttpContainerProvider, json_handler({"data": {"nope": 1}}))
    with pytest.raises(ProviderUnavailable) as e:
        await track(p)
    assert e.value.reason == "bad_payload"


@pytest.mark.parametrize("env", [{"FF_TRACKING_KILL_SWITCH": "1"}, {"FF_TRACKING_CONTAINER_DISABLED": "true"}])
async def test_kill_switch_makes_no_request(env):
    calls: list = []
    p, _ = make(HttpContainerProvider, json_handler(fx("container_ok.json"), calls), env=env)
    with pytest.raises(ProviderUnavailable) as e:
        await track(p)
    assert e.value.reason == "kill_switch" and calls == []


async def test_not_configured_and_cooldown_and_cache_and_host_throttle():
    p, _ = make(HttpContainerProvider, json_handler(fx("container_ok.json")), key="")
    with pytest.raises(ProviderUnavailable) as e:
        await track(p)
    assert e.value.reason == "not_configured"

    calls: list = []
    p, ft = make(HttpContainerProvider, json_handler(fx("container_ok.json"), calls), min_interval_s=0.1)
    assert p.min_interval_s == 3.0  # floor
    await track(p, container_no("MSKU", "000001"))
    await track(p, container_no("MSKU", "000002"))  # same host: must wait >= 3 s (fake clock)
    assert len(calls) == 2 and ft.slept and ft.slept[0] >= 2.99
    await track(p, container_no("MSKU", "000001"))  # cached: no new call
    assert len(calls) == 2

    state = {"n": 0}

    def flaky(request):
        state["n"] += 1
        return httpx.Response(500)

    p, ft = make(HttpContainerProvider, flaky)
    for _ in range(2):
        with pytest.raises(ProviderUnavailable):
            await track(p)
    assert state["n"] == 1  # second call short-circuited by the cooldown
    ft.t += 61
    with pytest.raises(ProviderUnavailable):
        await track(p)
    assert state["n"] == 2


async def test_fallback_to_mock_sets_warning_and_never_overwrites_real_data():
    bad, _ = make(HttpContainerProvider, lambda r: httpx.Response(503))
    fb = FallbackProvider(RoutingProvider(container=bad), MockProvider())
    snap = await track(fb)
    assert snap.provider == "mock" and snap.events and snap.warning == "provider_unavailable:upstream_error"
    killed, _ = make(HttpContainerProvider, json_handler(fx("container_ok.json")),
                     env={"FF_TRACKING_KILL_SWITCH": "on"})
    assert (await track(FallbackProvider(RoutingProvider(container=killed), MockProvider()))).warning \
        == "provider_unavailable:kill_switch"


# ---------------- service level: warning, outbox, job ----------------

class Switchable:
    """Provider whose behavior the test flips: real fixture payload or an outage."""

    id = "http"

    def __init__(self):
        self.payload = fx("container_delayed.json")
        self.down = False
        ft = FakeTime()
        self.real = HttpContainerProvider(
            "https://api.example.test", "k", cache_ttl_s=0, cooldown_s=0, env={}, clock=ft, sleep=ft.sleep,
            client=httpx.AsyncClient(transport=httpx.MockTransport(self._handle)))
        self.fb = FallbackProvider(RoutingProvider(container=self.real), MockProvider())

    def _handle(self, request):
        return httpx.Response(503) if self.down else httpx.Response(200, json=self.payload)

    async def track(self, *a, **kw):
        return await self.fb.track(*a, **kw)


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    clock.now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    sw = Switchable()
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db", refresh_min_interval_seconds=60)
    app = create_app(settings, provider=sw, clock=clock)
    with TestClient(app) as c:
        yield c, sw, clock, app


def outbox(app):
    import asyncio
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        app.state.service.repo.pending_outbox())


def test_outage_keeps_real_events_and_sets_warning(env):
    c, sw, clock, _ = env
    created = c.post("/v1/shipments", json={"reference": container_no(), "reference_type": "container"}, headers=H)
    assert created.status_code == 201
    sh = created.json()
    assert sh["provider"] == "http_container" and sh["warning"] is None and sh["events"][0]["source"] == "http_container"
    sw.down = True
    clock.advance(minutes=5)
    r = c.post(f"/v1/shipments/{sh['id']}/refresh", headers=H).json()
    assert r["warning"] == "provider_unavailable:upstream_error"
    assert [e["source"] for e in r["events"]] == ["http_container"]  # mock data did not replace real events
    sw.down = False
    clock.advance(minutes=5)
    assert c.post(f"/v1/shipments/{sh['id']}/refresh", headers=H).json()["warning"] is None


def test_outbox_emits_once_per_change_and_delay_flag(env):
    c, sw, clock, app = env
    ref = container_no()
    sh = c.post("/v1/shipments", json={"reference": ref, "reference_type": "container"}, headers=H).json()
    assert sh["status"] == "departed" and sh["delayed"] is False
    assert outbox(app) == []  # baseline fetch emits nothing
    sw.payload = fx("container_arrived.json")  # status -> out_for_delivery, eta slips 15 days -> delayed
    clock.advance(minutes=5)
    r = c.post(f"/v1/shipments/{sh['id']}/refresh", headers=H).json()
    assert r["status"] == "out_for_delivery" and r["delayed"] is False  # landed: stale-eta rule not applied
    rows = outbox(app)
    assert [x.kind for x in rows] == ["status_changed"]
    payload = json.loads(rows[0].payload)
    assert payload["status"] == "out_for_delivery" and payload["previous_status"] == "departed"
    assert payload["owner_id"] == "usr_a" and payload["delay_hours"] is None
    for _ in range(3):  # unchanged data => no more records
        clock.advance(minutes=5)
        c.post(f"/v1/shipments/{sh['id']}/refresh", headers=H)
    assert len(outbox(app)) == 1


def test_delay_notification_when_eta_slips(env):
    c, sw, clock, app = env
    sh = c.post("/v1/shipments", json={"reference": container_no(), "reference_type": "container"}, headers=H).json()
    assert sh["eta"].startswith("2026-10-25") and sh["delayed"] is False
    sw.payload = json.loads(json.dumps(sw.payload))
    sw.payload["data"]["eta"] = "2026-11-02T06:00:00Z"
    clock.advance(minutes=5)
    r = c.post(f"/v1/shipments/{sh['id']}/refresh", headers=H).json()
    assert r["delayed"] is True and r["delay_hours"] == 8 * 24 and r["initial_eta"].startswith("2026-10-25")
    assert [x.kind for x in outbox(app)] == ["shipment_delayed"]
    clock.advance(minutes=5)
    c.post(f"/v1/shipments/{sh['id']}/refresh", headers=H)
    assert len(outbox(app)) == 1


def test_refresh_job_respects_interval_and_emits_once(env):
    import asyncio
    c, sw, clock, app = env
    svc = app.state.service
    sh = c.post("/v1/shipments", json={"reference": container_no(), "reference_type": "container"}, headers=H).json()
    job = RefreshJob(svc.repo, svc, clock, interval_hours=6, batch_size=10)
    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(job.run_once()) == {"refreshed": 0, "failed": 0, "events": 0}
        sw.payload = fx("container_arrived.json")
        clock.advance(hours=7)
        assert loop.run_until_complete(job.run_once()) == {"refreshed": 1, "failed": 0, "events": 1}
        clock.advance(hours=1)  # too soon again
        assert loop.run_until_complete(job.run_once())["refreshed"] == 0
        clock.advance(hours=7)
        assert loop.run_until_complete(job.run_once())["events"] == 0  # no change, no record
        assert len(loop.run_until_complete(svc.repo.pending_outbox())) == 1
    finally:
        loop.close()
    assert c.get(f"/v1/shipments/{sh['id']}", headers=H).json()["status"] == "out_for_delivery"


def test_per_shipment_refresh_throttle_with_fake_clock(env):
    c, _, clock, _ = env
    sh = c.post("/v1/shipments", json={"reference": container_no(), "reference_type": "container"}, headers=H).json()
    r = c.post(f"/v1/shipments/{sh['id']}/refresh", headers=H)
    assert r.status_code == 429 and r.headers["Retry-After"]
    clock.advance(seconds=61)
    assert c.post(f"/v1/shipments/{sh['id']}/refresh", headers=H).status_code == 200


def test_default_provider_is_mock_and_http_without_config_degrades(tmp_path):
    from ff_tracking.main import build_provider
    assert isinstance(build_provider(Settings(database_url="sqlite+aiosqlite:///:memory:")), MockProvider)
    s = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/x.db", provider="http")  # no URLs/keys
    with TestClient(create_app(s)) as c:
        r = c.post("/v1/shipments", json={"reference": container_no(), "reference_type": "container"}, headers=H)
        assert r.status_code == 201 and r.json()["warning"] == "provider_unavailable:not_configured"
        assert r.json()["provider"] == "mock"
