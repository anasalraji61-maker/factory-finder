"""Identifier handling: ISO 6346 / AWB mod-7 / B/L tolerance, typo suggestions, carrier directory, status mapping."""

import json
from datetime import UTC, datetime

import pytest

from ff_tracking.domain.directory import _FILE, load_directory, suggest_carrier
from ff_tracking.domain.enums import ReferenceType as R
from ff_tracking.domain.enums import ShipmentStatus as S
from ff_tracking.domain.normalize import (
    CARRIER_STATUS_MAPS,
    STATUS_MAP,
    map_status,
    normalize_events,
    resolve_status,
)
from ff_tracking.domain.validators import (
    awb_check_digit,
    container_check_digit,
    validate_awb,
    validate_bl,
    validate_container,
)


# Published / well-formed examples (check digit computed with ISO 6346: sum(value * 2**i) % 11 % 10).
def _with_check(first10: str) -> str:
    return first10 + str(container_check_digit(first10))


@pytest.mark.parametrize("first10", ["CSQU305438", "MSCU663987", "TGHU750003", "HLXU123456", "ZIMU900001", "OOLU800123"])
def test_container_algorithm_round_trip(first10):
    ref = _with_check(first10)
    assert validate_container(ref).valid
    wrong = ref[:10] + str((int(ref[10]) + 1) % 10)
    assert validate_container(wrong).reason == "check_digit"


def test_container_published_example_and_digit_values():
    assert container_check_digit("CSQU305438") == 3
    assert validate_container("CSQU3054383").valid


@pytest.mark.parametrize("typo,fixed", [
    ("CSQU3O54383", "CSQU3054383"),   # letter O instead of zero
    ("MSCU663987O", "MSCU6639870"),   # O as the check digit
    ("CSQU3054383".replace("0", "O"), "CSQU3054383"),
    ("C5QU3054383", "CSQU3054383"),   # 5 instead of S in the owner code
])
def test_container_typo_suggestions(typo, fixed):
    v = validate_container(typo)
    assert not v.valid and fixed in v.suggestions


def test_container_i_for_one_and_digit_for_letter():
    first10 = next(f"MSCU{n:06d}" for n in range(100000, 200000) if "1" in f"{n:06d}"
                   and _with_check(f"MSCU{n:06d}").count("1") >= 1)
    good = _with_check(first10)
    typo = good.replace("1", "I", 1)
    assert typo != good and good in validate_container(typo).suggestions
    assert validate_container("0SCU" + good[4:]).valid is False


def test_container_no_suggestion_for_garbage_and_valid_has_none():
    assert validate_container("HELLO").suggestions == ()
    assert validate_container("CSQU3054383").suggestions == ()
    assert len(validate_container("OOOOOOOOOOO").suggestions) <= 3


def test_awb_mod7_and_tolerance():
    serial = "1234567"
    num = f"176{serial}{int(serial) % 7}"
    assert awb_check_digit(serial) == int(serial) % 7 == 5
    for form in (num, "176-12345675", "176 1234 5675", "176.12345675", "176/12345675"):
        assert validate_awb(form).normalized == "176-12345675" and validate_awb(form).valid
    assert validate_awb("176-12345676").reason == "check_digit"
    assert "176-12345675" in validate_awb("176-1234567S").suggestions


@pytest.mark.parametrize("raw,norm,prefix", [
    ("MAEU 123456789", "MAEU123456789", "MAEU"),
    ("B/L No.: COSU6123456780", "COSU6123456780", "COSU"),
    ("bl# hlcu-sha-2301abc1", "HLCUSHA2301ABC1", "HLCU"),
    ("MEDU/XX123456", "MEDUXX123456", "MEDU"),
    ("123456789012", "123456789012", None),
])
def test_bl_tolerant(raw, norm, prefix):
    v = validate_bl(raw)
    assert v.valid and v.normalized == norm and v.prefix == prefix


@pytest.mark.parametrize("raw", ["", "AB1", "12345678", "AB!!", "X" * 30])
def test_bl_rejects(raw):
    assert not validate_bl(raw).valid


# ---- directory -------------------------------------------------------------------------------------------------

def test_directory_shape_and_size():
    d = load_directory()
    assert d.as_of == "2026-10"
    assert json.loads(_FILE.read_text(encoding="utf-8"))["indicative"] is True
    assert len(d.ocean) >= 40 and len(d.airlines) >= 60


def test_directory_prefixes_unique_and_wellformed():
    d = load_directory()
    seen: dict[str, str] = {}
    for c in d.ocean:
        for p in c["container_prefixes"]:
            assert len(p) == 4 and p[3] == "U" and p not in d.lessor_prefixes, p
            assert seen.setdefault(p, c["code"]) == c["code"], p
        assert c["scac"] is None or len(c["scac"]) in (4,)
    awb = [a["awb_prefix"] for a in d.airlines]
    assert all(len(p) == 3 and p.isdigit() for p in awb) and len(awb) == len(set(awb))
    codes = [x["code"] for x in (*d.ocean, *d.airlines)]
    assert len(codes) == len(set(codes))


def test_directory_agrees_with_static_table():
    from ff_tracking.domain.carriers import AIRLINES, OCEAN_CARRIERS

    for c in OCEAN_CARRIERS:
        for p in (x for x in c.container_prefixes if x[3] in "UJZ"):  # EGLV is a SCAC, not a BIC code
            assert suggest_carrier(R.CONTAINER, p).code == c.code
    for a in AIRLINES:
        assert suggest_carrier(R.AWB, a.awb_prefix).code == a.code


@pytest.mark.parametrize("rtype,prefix,code", [
    (R.CONTAINER, "MSCU", "msc"), (R.CONTAINER, "MSKU", "maersk"), (R.CONTAINER, "APLU", "apl"),
    (R.BL, "COSU", "cosco"), (R.BL, "SUDU", "maersk"), (R.AWB, "176", "emirates"), (R.AWB, "999", "air_china"),
    (R.AWB, "288", "air_hong_kong"),
])
def test_suggest_carrier(rtype, prefix, code):
    s = suggest_carrier(rtype, prefix)
    assert s and s.code == code and s.as_of == "2026-10" and s.indicative


def test_suggest_carrier_none_cases():
    assert suggest_carrier(R.CONTAINER, "TGHU") is None  # leasing company: any carrier
    assert suggest_carrier(R.CONTAINER, "ZZZU") is None
    assert suggest_carrier(R.AWB, "000") is None
    assert suggest_carrier(R.VESSEL_IMO, "9074729") is None and suggest_carrier(R.AWB, None) is None


def test_validate_endpoint_carrier_suggestion(client):
    first = "APLU123456"
    ref = first + str(container_check_digit(first))
    ok = client.get(f"/v1/validate/container/{ref}").json()
    assert ok["valid"] and ok["carrier_suggestion"]["code"] == "apl" and ok["suggestions"] == []
    assert ok["carrier_suggestion"]["basis"] == "container_owner_prefix"
    typo = client.get("/v1/validate/container/CSQU3O54383").json()
    assert not typo["valid"] and typo["suggestions"] == ["CSQU3054383"] and typo["carrier_suggestion"] is None
    awb = client.get("/v1/validate/awb/176-12345675").json()
    assert awb["carrier_suggestion"]["basis"] == "awb_prefix" and awb["carrier_suggestion"]["iata_code"] == "EK"


# ---- status mapping ---------------------------------------------------------------------------------------------

def test_status_map_values_are_statuses_and_cover_every_status():
    assert set(STATUS_MAP.values()) | {S.IN_TRANSIT} >= set(S) - {S.IN_TRANSIT}
    for table in CARRIER_STATUS_MAPS.values():
        assert all(isinstance(v, S) for v in table.values())


@pytest.mark.parametrize("code,expected", sorted(STATUS_MAP.items()))
def test_default_mapping_each(code, expected):
    assert map_status(code.lower().replace("_", " ")) is expected


@pytest.mark.parametrize("carrier,code,expected",
                         [(c, k, v) for c, t in sorted(CARRIER_STATUS_MAPS.items()) for k, v in sorted(t.items())])
def test_carrier_mapping_each(carrier, code, expected):
    assert map_status(code, carrier) is expected


def test_carrier_table_overrides_default_and_dcsa_fallback():
    assert map_status("GATE_IN_EMPTY", "one") is S.DELIVERED
    assert map_status("GATE_OUT_EMPTY", "one") is S.BOOKED
    assert map_status("GTOT") is S.OUT_FOR_DELIVERY  # generic DCSA profile as last resort
    assert map_status("EXPORT_LOADED_ON_VESSEL", "msc") is S.LOADED
    assert map_status("EXPORT_LOADED_ON_VESSEL", "maersk") is None


def test_unknown_fallback_never_moves_or_reopens():
    assert map_status("WHAT_IS_THIS") is None
    assert resolve_status("WHAT_IS_THIS", None, S.DEPARTED) is S.DEPARTED
    assert resolve_status("WHAT_IS_THIS") is S.BOOKED
    assert resolve_status("WHAT_IS_THIS", "msc", S.DELIVERED) is S.DELIVERED
    assert resolve_status("LOADED", "msc", S.DELIVERED) is S.DELIVERED
    assert resolve_status("DISCHARGED", None, S.DEPARTED) is S.DISCHARGED


def test_normalize_events_uses_carrier_table_and_skips_unknown_after_delivered():
    now = datetime(2026, 10, 15, tzinfo=UTC)
    raw = [
        {"code": "Export Loaded on Vessel", "timestamp": "2026-10-01T00:00:00Z", "hub": "CNSHA"},
        {"code": "DELIVERED", "timestamp": "2026-10-10T00:00:00Z", "hub": "SAJED"},
        {"code": "SOME_NEW_CARRIER_CODE", "timestamp": "2026-10-11T00:00:00Z"},
    ]
    events, _, _, skipped = normalize_events(raw, source="t", now=now, carrier_code="msc")
    assert [e.status for e in events] == [S.LOADED, S.DELIVERED] and skipped == 1
    events2, *_ = normalize_events(raw[:1], source="t", now=now)
    assert events2 == []  # carrier-specific name is unknown for the default table
