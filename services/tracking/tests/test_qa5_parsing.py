"""QA: reference parsing (ISO 6346, AWB mod 7, B/L prefixes, IMO), ambiguity, status table, ETA threshold, timezones."""
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ff_tracking.domain import normalize as nz
from ff_tracking.domain.detect import detect_reference
from ff_tracking.domain.enums import ReferenceType as R
from ff_tracking.domain.enums import ShipmentStatus as S
from ff_tracking.domain.eta import assess_eta
from ff_tracking.domain.validators import (
    awb_check_digit,
    container_check_digit,
    validate_awb,
    validate_bl,
    validate_container,
    validate_imo,
)

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def _cont(first10: str) -> str:
    return first10 + str(container_check_digit(first10))


@pytest.mark.parametrize("raw", ["CSQU3054383", "csqu3054383", " csqu 305438 3 ", "CSQU-305438-3", "csqu-3054383\t"])
def test_container_valid_variants(raw):
    v = validate_container(raw)
    assert v.valid and v.normalized == "CSQU3054383" and v.prefix == "CSQU"


def test_container_invalid_check_digit_and_format():
    assert validate_container("CSQU3054384").reason == "check_digit"
    assert validate_container("CSQ3054383").reason.startswith("format")
    assert validate_container("CSQX3054383").reason.startswith("format")  # category must be U/J/Z


def _ref_digit(first10: str) -> int:
    vals, n = {}, 10
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        n += n % 11 == 0
        vals[ch] = n
        n += 1
    return sum((vals[c] if c.isalpha() else int(c)) * 2**i for i, c in enumerate(first10)) % 11 % 10


def test_container_check_digit_matches_independent_impl_incl_remainder_10():
    for n in range(0, 3000, 7):
        first = f"ABCU{n:06d}"
        assert container_check_digit(first) == _ref_digit(first)
    # known published example values (ISO 6346 annex style)
    assert container_check_digit("CSQU305438") == 3 and container_check_digit("MSKU907009") == _ref_digit("MSKU907009")
    zero = next(f"ABCU{n:06d}" for n in range(10**4) if _ref_digit(f"ABCU{n:06d}") == 0)
    assert validate_container(zero + "0").valid


def test_awb_mod7():
    assert validate_awb("176-12345675").valid
    assert validate_awb("176 1234 5675").normalized == "176-12345675"
    assert validate_awb("17612345676").reason == "check_digit"
    assert awb_check_digit("1234567") == 1234567 % 7
    assert not validate_awb("1761234567").valid and not validate_awb("176123456750").valid


def test_awb_serial_check_digit_ignores_prefix():
    assert validate_awb("001-12345675").valid and validate_awb("999-12345675").valid


@pytest.mark.parametrize("bl,ok_fmt", [
    ("MAEU123456789", True), ("MSCUAB123456", True), ("CMDUABC1234567", True), ("COSU1234567890", True),
    ("HLCUXYZ12345678", True), ("ONEYABCD12345678", True), ("EGLV123456789012", True),
    ("EGLV12345", False), ("COSU12345678", False), ("MAEUABC12345", False)])
def test_bl_carrier_prefixes(bl, ok_fmt):
    v = validate_bl(bl)
    assert v.valid and v.prefix == bl[:4]
    assert (not v.warnings) is ok_fmt


def test_bl_noise_and_lowercase():
    v = validate_bl("B/L No.: maeu-123 456 789")
    assert v.valid and v.normalized == "MAEU123456789"
    assert not validate_bl("MAEU12").valid and not validate_bl("12AB34567890").valid


def test_imo():
    assert validate_imo("9074729").valid and validate_imo("imo 9074729").valid and validate_imo("IMO: 907-4729").valid
    assert validate_imo("9074728").reason == "check_digit"
    assert not validate_imo("0074729").valid and not validate_imo("907472").valid


# ---- ambiguity
def test_unique_types_are_high_confidence():
    c = detect_reference("CSQU3054383")
    assert [x.reference_type for x in c] == [R.CONTAINER, R.BL][:len(c)] and all(x.confidence == "medium" for x in c)
    assert [(x.reference_type, x.confidence) for x in detect_reference("9074729")] == [(R.VESSEL_IMO, "high")]


def test_awb_digits_also_look_like_bl_so_capped_medium():
    c = detect_reference("176-12345675")
    assert {x.reference_type for x in c} == {R.AWB, R.BL}
    assert all(x.confidence == "medium" for x in c)


def test_valid_container_also_bl_shape_capped_medium():
    c = detect_reference("csqu 3054383")
    assert {x.reference_type for x in c} == {R.CONTAINER, R.BL} and {x.confidence for x in c} == {"medium"}
    assert c[0].reference_type is R.CONTAINER  # most specific first


def test_bad_check_digit_container_is_not_offered_as_container():
    assert [x.reference_type for x in detect_reference("CSQU3054384")] == [R.BL]
    assert detect_reference("CSQU3054384")[0].confidence == "medium"  # not a carrier-format B/L number


def test_garbage_has_no_candidates():
    assert detect_reference("hello world!") == [] and detect_reference("") == []


def test_never_high_when_multiple():
    for raw in ["CSQU3054383", "17612345675", "MAEU123456789", "123456789"]:
        c = detect_reference(raw)
        assert len(c) == 1 or all(x.confidence != "high" for x in c)


# ---- status table
_MAP = json.loads((Path(nz.__file__).parent.parent / "data" / "status_map.json").read_text(encoding="utf-8"))


def test_every_raw_status_maps_to_canonical():
    valid = {s.value for s in S}
    assert _MAP["default"] and _MAP["carriers"]
    for table in (_MAP["default"], *_MAP["carriers"].values()):
        for k, v in table.items():
            assert v in valid, (k, v)
            assert nz.norm_code(k) == k, f"key {k} not upper-snake"
    for k in _MAP["default"]:
        assert nz.map_status(k) is S(_MAP["default"][k])
    for carrier, table in _MAP["carriers"].items():
        for k, v in table.items():
            assert nz.map_status(k, carrier) is S(v), (carrier, k)


def test_every_canonical_status_is_reachable_and_described():
    reachable = set(_MAP["default"].values())
    assert reachable == {s.value for s in S}
    assert all(s in nz.DESC_EN and s in nz.DESC_AR for s in S)


def test_unknown_status_does_not_move_shipment_and_is_counted():
    assert nz.map_status("TOTALLY_NEW_CODE") is None and nz.map_status(None) is None
    assert nz.resolve_status("TOTALLY_NEW_CODE", None, S.DEPARTED) is S.DEPARTED
    assert nz.resolve_status("nonsense", None, None) is S.BOOKED
    ev, eta, ms, skipped = nz.normalize_events(
        [{"code": "WEIRD", "timestamp": "2026-10-01T00:00:00Z"},
         {"code": "dep", "timestamp": "2026-10-01T00:00:00Z", "hub": "CNSHA"}], source="t", now=NOW)
    assert skipped == 1 and [e.status for e in ev] == [S.DEPARTED]


def test_status_code_spelling_is_normalised():
    assert nz.map_status("Vessel Departure") is S.DEPARTED and nz.map_status("gate-out-full") is S.OUT_FOR_DELIVERY


# ---- ETA thresholds (documented tolerance: slip > 12 h, see docs/decisions/tracking-providers.md)
def _delay(slip_h: float, status=S.IN_TRANSIT):
    init = NOW + timedelta(days=10)
    return assess_eta(init + timedelta(hours=slip_h), init, status, NOW)


def test_eta_slip_boundaries():
    assert _delay(11.9)[2] is False
    assert _delay(12)[2] is False  # strictly greater than the tolerance
    assert _delay(12.1)[2] is True
    assert _delay(24)[2] is True and _delay(24)[3] == 24
    assert _delay(23.5)[3] == 23


def test_early_arrival_never_flags_delay():
    for h in (-1, -30, -200):
        eta, init, delayed, hours = _delay(h)
        assert delayed is False and hours is None and init == NOW + timedelta(days=10)
    init = NOW - timedelta(days=2)
    assert assess_eta(init - timedelta(hours=40), init, S.ARRIVED, NOW, actual_arrival=init - timedelta(hours=40))[2] is False


# ---- timezones
def test_timestamps_normalised_to_utc():
    assert nz.parse_ts("2026-10-01T08:00:00+08:00") == datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
    assert nz.parse_ts("2026-10-01T00:00:00") == datetime(2026, 10, 1, tzinfo=UTC)  # naive = UTC
    assert nz.parse_ts("2026-10-01 00:00 UTC") == datetime(2026, 10, 1, tzinfo=UTC)
    assert nz.parse_ts(1_790_000_000) == nz.parse_ts(1_790_000_000_000)
    assert nz.parse_ts("2026-10-01T00:00:00-05:00").utcoffset() == timedelta(0)
    assert nz.parse_ts("garbage") is None


def test_same_instant_different_offsets_dedupe_and_future_detection():
    a = {"code": "DEP", "timestamp": "2026-10-01T08:00:00+08:00", "hub": "CNSHA"}
    b = {"code": "DEP", "timestamp": "2026-09-30T20:00:00-04:00", "hub": "CNSHA"}
    ev, *_ = nz.normalize_events([a, b], source="t", now=NOW)
    assert len(ev) == 1 and ev[0].timestamp.tzinfo is not None and ev[0].timestamp.utcoffset() == timedelta(0)
    # a +14:00 timestamp that looks like "tomorrow" locally is still in the past in UTC
    now = datetime(2026, 10, 15, 12, 0, tzinfo=timezone(timedelta(hours=-8)))
    ev, *_ = nz.normalize_events([{"code": "DEP", "timestamp": "2026-10-16T01:00:00+14:00"}], source="t", now=now)
    assert len(ev) == 1
