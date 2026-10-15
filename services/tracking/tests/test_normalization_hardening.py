"""Normalization hardening: dedupe across polls, ordering, offsets, ETA vs actual, multi-leg, vessel/IMO, B/L, owner codes.

No network: DCSA-shaped payloads from ``fixtures`` go through ``HttpContainerProvider.parse``.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ff_tracking.adapters.http import HttpAwbProvider, HttpContainerProvider
from ff_tracking.domain.carriers import (
    AIRLINES,
    LEASING_OWNER_PREFIXES,
    OCEAN_CARRIERS,
    carrier_for_bl_prefix,
    carrier_for_container_owner,
)
from ff_tracking.domain.enums import ShipmentStatus as S
from ff_tracking.domain.eta import assess_eta
from ff_tracking.domain.models import Shipment, TrackingSnapshot
from ff_tracking.domain.normalize import normalize_events, parse_flight, parse_ts
from ff_tracking.domain.validators import (
    clean_vessel_name,
    container_check_digit,
    imo_check_ok,
    parse_vessel,
    validate_bl,
    validate_container,
    validate_imo,
)

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def fx(name):
    return json.loads((FIX / name).read_text())


def raw(code, ts, hub="CNSHA", **kw):
    return {"code": code, "timestamp": ts, "hub": hub, **kw}


def norm(events, **kw):
    return normalize_events(events, source="t", now=kw.pop("now", NOW), **kw)


# ---- ordering / dedupe / timezones ----

def test_same_event_in_two_polls_collapses_and_latest_copy_wins():
    poll1 = [raw("LOADED", "2026-09-09T12:00:00Z", event_id="x1", description="old")]
    poll2 = [raw("LOADED", "2026-09-09T12:05:00Z", event_id="x1", description="corrected")]
    ev, *_ = norm(poll1 + poll2)
    assert len(ev) == 1 and ev[0].description == "corrected"
    assert ev[0].timestamp == datetime(2026, 9, 9, 12, 5, tzinfo=UTC)


@pytest.mark.parametrize("a,b,same", [
    ("2026-09-05T08:00:59Z", "2026-09-05T08:01:01Z", True),   # straddles a minute boundary
    ("2026-09-05T08:00:00Z", "2026-09-05T08:05:00Z", False),
    ("2026-09-05T08:00:00+08:00", "2026-09-05T00:00:30Z", True),  # same instant, different offsets
])
def test_dedupe_without_ids_uses_time_window(a, b, same):
    ev, *_ = norm([raw("GATE_IN", a), raw("GATE_IN", b)])
    assert (len(ev) == 1) is same


def test_different_hub_or_status_never_collapses():
    ev, *_ = norm([raw("GATE_IN", "2026-09-05T08:00:00Z", "CNSHA"), raw("GATE_IN", "2026-09-05T08:00:10Z", "CNNGB"),
                   raw("LOADED", "2026-09-05T08:00:20Z", "CNSHA")])
    assert len(ev) == 3


def test_out_of_order_input_is_sorted_and_ties_follow_progress():
    ev, *_ = norm([raw("DEPARTED", "2026-09-10T10:00:00Z"), raw("LOADED", "2026-09-10T10:00:00Z"),
                   raw("GATE_IN", "2026-09-05T00:00:00Z")])
    assert [e.status for e in ev] == [S.GATE_IN, S.LOADED, S.DEPARTED]


@pytest.mark.parametrize("text,expected", [
    ("2026-09-05T08:00:00+0800", datetime(2026, 9, 5, 0, 0, tzinfo=UTC)),
    ("2026-09-05T08:00:00-05:00", datetime(2026, 9, 5, 13, 0, tzinfo=UTC)),
    ("2026-09-05T08:00:00 GMT", datetime(2026, 9, 5, 8, 0, tzinfo=UTC)),
    ("2026-09-05T08:00:00utc", datetime(2026, 9, 5, 8, 0, tzinfo=UTC)),
    ("2026-09-05T08:00:00", datetime(2026, 9, 5, 8, 0, tzinfo=UTC)),
    ("garbage", None), ("", None), (None, None), (True, None), (float("nan"), None),
])
def test_parse_ts_offsets(text, expected):
    assert parse_ts(text) == expected


def test_clock_skew_tolerance_for_explicit_actual_only():
    soon = (NOW + timedelta(minutes=5)).isoformat()
    assert len(norm([raw("DEPARTED", soon, actual=True)])[0]) == 1
    assert norm([raw("DEPARTED", soon)])[0] == []  # no explicit flag: treated as planned
    assert norm([raw("DEPARTED", (NOW + timedelta(hours=2)).isoformat(), actual=True)])[0] == []


# ---- ETA vs actual, delays, exceptions ----

def test_planned_arrival_at_transshipment_hub_is_not_the_eta():
    ev, eta, *_ = norm([raw("ARRIVAL", "2026-10-08T00:00:00Z", "MYPKG", actual=False),
                        raw("ARRIVAL", "2026-10-23T00:00:00Z", "IQUQR", actual=False)], destination_hub="IQUQR")
    assert ev == [] and eta == datetime(2026, 10, 23, tzinfo=UTC)


def test_unknown_destination_uses_the_last_planned_arrival():
    _, eta, *_ = norm([raw("ARRIVAL", "2026-10-08T00:00:00Z", "MYPKG", actual=False),
                       raw("ARRIVAL", "2026-10-23T00:00:00Z", "IQUQR", actual=False)])
    assert eta == datetime(2026, 10, 23, tzinfo=UTC)


def test_estimate_supersedes_plan_even_when_later():
    _, eta, *_ = norm([
        raw("ARRIVAL", "2026-10-20T00:00:00Z", "IQUQR", actual=False, classifier="PLN", created="2026-09-01T00:00:00Z"),
        raw("ARRIVAL", "2026-10-25T00:00:00Z", "IQUQR", actual=False, classifier="EST", created="2026-09-28T00:00:00Z")],
        destination_hub="IQUQR")
    assert eta == datetime(2026, 10, 25, tzinfo=UTC)


def test_assess_eta_actual_arrival_decides_delay():
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    late = assess_eta(t0, t0, S.ARRIVED, t0 + timedelta(days=9), actual_arrival=t0 + timedelta(days=3))
    assert late[2] is True and late[3] == 72
    ok = assess_eta(t0, t0, S.DELIVERED, t0 + timedelta(days=9), actual_arrival=t0 + timedelta(hours=5))
    assert ok[2] is False and ok[3] is None
    early = assess_eta(t0, t0, S.ARRIVED, t0 + timedelta(days=9), actual_arrival=t0 - timedelta(days=2))
    assert early[2] is False


def test_exception_state_keeps_progress_and_stale_eta_is_delayed():
    from ff_tracking.domain.progress import progress_percent
    ev, *_ = norm([raw("DEPARTED", "2026-09-10T00:00:00Z"), raw("DELAYED", "2026-09-12T00:00:00Z", "MYPKG")])
    assert ev[-1].status is S.EXCEPTION and progress_percent(S.EXCEPTION, ev) == 35
    eta, init, delayed, hours = assess_eta(NOW - timedelta(days=3), NOW - timedelta(days=3), S.EXCEPTION, NOW)
    assert delayed and eta == NOW + timedelta(hours=24) and hours == 72


def _shipment():
    return Shipment(id="s", owner_id="u", reference="MSKU0000000", reference_type="container",
                    created_at=NOW, updated_at=NOW)


def test_second_poll_with_shorter_history_does_not_drop_events():
    p = HttpContainerProvider("https://x.test", "k")
    full = p.parse(fx("dcsa_multileg.json"), now=NOW)
    partial_payload = {"events": [e for e in fx("dcsa_multileg.json")["events"] if e["eventID"] in {"d6", "d5"}]}
    partial = p.parse(partial_payload, now=NOW + timedelta(hours=1))
    sh = _shipment()
    sh.apply_snapshot(full, NOW)
    n = len(sh.events)
    sh.apply_snapshot(partial, NOW + timedelta(hours=1))
    assert len(sh.events) == n and sh.status == full.status


def test_delivered_shipment_is_not_reopened():
    sh = _shipment()
    sh.apply_snapshot(TrackingSnapshot(provider="p", fetched_at=NOW, events=tuple(
        norm([raw("DELIVERED", "2026-10-01T00:00:00Z", "IQUQR")])[0])), NOW)
    sh.apply_snapshot(TrackingSnapshot(provider="p", fetched_at=NOW, events=tuple(
        norm([raw("DEPARTED", "2026-09-01T00:00:00Z")])[0])), NOW)
    assert sh.status is S.DELIVERED


# ---- DCSA multi-leg ocean ----

def test_dcsa_multileg_timeline():
    p = HttpContainerProvider("https://x.test", "k")
    payload = {**fx("dcsa_multileg.json"), "destination": "IQUQR", "origin": "CNSHA"}
    snap = p.parse(payload, now=NOW)
    assert [e.status for e in snap.events] == [
        S.BOOKED, S.GATE_IN, S.LOADED, S.DEPARTED, S.TRANSSHIPMENT, S.LOADED, S.DEPARTED]
    assert [e.timestamp for e in snap.events] == sorted(e.timestamp for e in snap.events)
    assert snap.events[1].timestamp == datetime(2026, 9, 5, 0, 0, tzinfo=UTC)
    assert snap.eta == datetime(2026, 10, 23, 3, 0, tzinfo=UTC)  # EST at the destination, +03:00 -> UTC
    assert snap.vessel.name == "EVER GIVEN" and snap.vessel.imo == "9811000" and snap.vessel.voyage == "413E"
    assert snap.events[3].vessel.imo == "9074729"
    assert set(snap.milestones) == {"gate_in", "loaded", "departed", "transshipment"}
    assert snap.status is S.DEPARTED  # second leg under way


def test_dcsa_without_destination_never_picks_a_transshipment_arrival_as_final():
    snap = HttpContainerProvider("https://x.test", "k").parse(fx("dcsa_multileg.json"), now=NOW)
    assert snap.eta == datetime(2026, 10, 23, 3, 0, tzinfo=UTC)
    assert S.ARRIVED not in {e.status for e in snap.events}


def test_dcsa_bad_payload_is_unusable():
    from ff_tracking.adapters.base import ProviderUnavailable
    with pytest.raises(ProviderUnavailable):
        HttpContainerProvider("https://x.test", "k").parse({"events": [1]}, now=NOW)


# ---- AWB multi-leg ----

def test_awb_two_flights_timeline():
    snap = HttpAwbProvider("https://x.test", "k").parse(fx("awb_multileg.json"), now=NOW, reference="176-12345675")
    assert [e.status for e in snap.events] == [S.GATE_IN, S.DEPARTED, S.TRANSSHIPMENT, S.DEPARTED, S.ARRIVED]
    assert [e.flight.number if e.flight else None for e in snap.events] == [None, "EK306", "EK306", "EK941", "EK941"]
    assert snap.events[-1].timestamp == datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
    assert snap.flight.number == "EK941" and snap.flight.carrier_code == "EK" and snap.status is S.ARRIVED


@pytest.mark.parametrize("v,num", [("ek 306", "EK306"), ("EK0306", "EK306"), ("5X123", "5X123"), ("3U8888", "3U8888"),
                                   ("", None), ("Emirates", None), (None, None)])
def test_parse_flight(v, num):
    f = parse_flight(v)
    assert (f.number if f else None) == num


# ---- vessel / IMO ----

KNOWN_IMO = ["9074729", "9811000", "9321483", "9776171"]


@pytest.mark.parametrize("imo", KNOWN_IMO)
def test_known_imos_pass(imo):
    assert imo_check_ok(imo) and validate_imo(imo).valid


@pytest.mark.parametrize("raw_imo,ok", [
    ("IMO 9074729", True), ("imo9074729", True), ("IMO: 9074729", True), ("IMO-9074729", True),
    ("9074729", True), ("9074720", False), ("0000000", False), ("907472", False), ("90747290", False),
    ("IMO", False), ("", False), ("ABCDEFG", False)])
def test_imo_formats(raw_imo, ok):
    assert validate_imo(raw_imo).valid is ok


@pytest.mark.parametrize("name,expected", [
    ("M/V EVER GIVEN", "EVER GIVEN"), ("mv  ever  given", "EVER GIVEN"), ("MSC GULSUN", "MSC GULSUN"),
    ("MSC GULSUN (IMO 9811000)", "MSC GULSUN"), ("M.V. Maersk Sentosa", "MAERSK SENTOSA"),
    ("MT Atlantic", "ATLANTIC"), ("MSCHIEF", "MSCHIEF"), ("  ‮COSCO​ SHIPPING  ", "COSCO SHIPPING"),
    ("", None), (None, None), ("M/V ", None)])
def test_clean_vessel_name(name, expected):
    assert clean_vessel_name(name) == expected


def test_parse_vessel_imo_variants():
    assert parse_vessel({"name": "MSC GULSUN (IMO 9811000)"}).imo == "9811000"
    assert parse_vessel({"name": "X", "imo": "IMO 9074729"}).imo == "9074729"
    v = parse_vessel({"name": "X", "imo": "9074728", "voyage": " 12e "})  # bad check digit: name kept, IMO dropped
    assert v.imo is None and v.name == "X" and v.voyage == "12E"
    assert parse_vessel({"imo": "9074729"}) is None and parse_vessel("MAERSK") is None


# ---- B/L formats ----

@pytest.mark.parametrize("text,norm_ref,warn", [
    ("MAEU261234567", "MAEU261234567", ()),
    ("B/L No.: MAEU 261234567", "MAEU261234567", ()),
    ("261234567", "261234567", ()),
    ("MEDUQ1234567", "MEDUQ1234567", ()),
    ("COSU6123456789", "COSU6123456789", ()),
    ("COSU612345", "COSU612345", ("unusual_format:cosco",)),
    ("EGLV143500123456", "EGLV143500123456", ()),
    ("HLCUSHA210112345", "HLCUSHA210112345", ()),
    ("ONEYSHAZ12345600", "ONEYSHAZ12345600", ()),
    ("OOLU2123456789", "OOLU2123456789", ()),
    ("YMLUW123456789", "YMLUW123456789", ()),
    ("bill of lading no. ZIMUSHA12345678", "ZIMUSHA12345678", ()),
    ("BL: CMDUSHA1234567", "CMDUSHA1234567", ()),
    ("BOLU12345678", "BOLU12345678", ()),   # not a "BOL" label: the B is part of the number
    ("BLNU1234567890", "BLNU1234567890", ()),
    ("HDMUSHAZ12345600", "HDMUSHAZ12345600", ()),
])
def test_bl_per_carrier_formats(text, norm_ref, warn):
    v = validate_bl(text)
    assert v.valid and v.normalized == norm_ref and v.warnings == warn


@pytest.mark.parametrize("text", ["", "MAEU", "12345678", "AB-12", "MAEU 2612#34567!", "X" * 21, "1234ABCD99"])
def test_bl_rejects(text):
    assert not validate_bl(text).valid


# ---- ISO 6346 / owner-code registry sanity ----

def _independent_check_digit(ten: str) -> int:
    values, n = {}, 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        n += n % 11 == 0
        values[ch] = n
        n += 1
    return sum((values[c] if c.isalpha() else int(c)) * 2 ** i for i, c in enumerate(ten)) % 11 % 10


def test_known_valid_containers_and_check_digit_ten_maps_to_zero():
    assert validate_container("CSQU3054383").valid and not validate_container("CSQU3054380").valid
    for serial in range(3000):
        ten = f"MSCU{serial:06d}"
        digit = container_check_digit(ten)
        assert digit == _independent_check_digit(ten) and validate_container(f"{ten}{digit}").valid
    assert any(_raw_remainder(f"MSCU{s:06d}") == 10 for s in range(3000))  # the remainder-10 -> 0 rule is exercised


def _raw_remainder(ten: str) -> int:
    values, n = {}, 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        n += n % 11 == 0
        values[ch] = n
        n += 1
    return sum((values[c] if c.isalpha() else int(c)) * 2 ** i for i, c in enumerate(ten)) % 11


def test_owner_code_registry_sanity():
    owners = [p for c in OCEAN_CARRIERS for p in c.container_prefixes]
    assert all(len(p) == 4 and p.isalpha() and p.isupper() and p[3] in "UJZ" for p in owners)
    assert len(owners) == len(set(owners)), "an owner code can belong to one carrier only"
    assert not set(owners) & LEASING_OWNER_PREFIXES
    assert all(len(p) == 4 and p.isalpha() and p[3] in "UJZ" for p in LEASING_OWNER_PREFIXES)
    for c in OCEAN_CARRIERS:
        assert c.scac and len(c.scac) == 4 and c.container_prefixes and c.bl_prefixes
        assert carrier_for_bl_prefix(c.scac) is c
        for p in c.container_prefixes:
            assert carrier_for_container_owner(p) is c
        for p in c.bl_prefixes:
            assert len(p) == 4 and p.isalpha()


def test_airline_table_sanity():
    assert all(c.awb_prefix and len(c.awb_prefix) == 3 and c.awb_prefix.isdigit() for c in AIRLINES)
    assert all(c.iata_code and len(c.iata_code) == 2 for c in AIRLINES)
    assert len({c.iata_code for c in AIRLINES}) == len(AIRLINES)
