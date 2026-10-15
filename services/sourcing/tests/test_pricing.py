"""Price / unit / condition / year normalization (domain/pricing.py). Fixture: tests/fixtures/price_unit_cases.json.

Money stays Decimal (strings in the fixture); ambiguity is flagged, never guessed. No network.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from ff_sourcing.domain.pricing import (
    UnitConversionError,
    convert_unit_price,
    detect_currency_ex,
    normalize_unit,
    parse_condition,
    parse_number,
    parse_price_text,
    parse_year,
)

FIX = json.loads((Path(__file__).parent / "fixtures" / "price_unit_cases.json").read_text(encoding="utf-8"))
CASES = FIX["cases"]


def _ids(kind):
    return [c for c in CASES if c["kind"] == kind]


def test_fixture_has_at_least_60_cases_and_decimal_strings():
    assert len(CASES) >= 60
    for c in _ids("price"):
        for k in ("price_min", "price_max"):
            assert c[k] is None or isinstance(c[k], str)


@pytest.mark.parametrize("c", _ids("price"), ids=lambda c: c["text"])
def test_price_cases(c):
    r = parse_price_text(c["text"], country=c.get("country"))
    d = r.to_dict()
    assert d["price_min"] == c["price_min"] and d["price_max"] == c["price_max"]
    if c["price_min"] is not None:  # Decimal, exact, never float
        assert isinstance(r.price_min, Decimal) and str(r.price_min) == c["price_min"]
    assert r.currency == c["currency"], d
    assert r.unit == c["unit"], d
    for k in ("moq", "pack_qty", "is_from", "is_up_to"):
        if k in c:
            assert d[k] == c[k], (k, d)
    if "candidates" in c:
        assert d["currency_candidates"] == c["candidates"]
    if "tiers" in c:
        assert [[t["min_qty"], t["max_qty"], t["price_min"]] for t in d["tiers"]] == c["tiers"]
    assert set(c.get("flags", [])) <= set(d["flags"]), d
    if c["currency"] is None and c["price_min"] is not None and c.get("candidates"):
        assert any(f.startswith("ambiguous_") for f in d["flags"])  # never silently guessed


@pytest.mark.parametrize("c", _ids("condition"), ids=lambda c: c["text"])
def test_condition_cases(c):
    cond, flags = parse_condition(c["text"])
    assert cond == c["condition"]
    assert set(c["flags"]) <= set(flags)
    if cond is None and c["flags"]:
        assert all(f.startswith("ambiguous_") for f in flags)


@pytest.mark.parametrize("c", _ids("year"), ids=lambda c: c["text"])
def test_year_cases(c):
    y, flags = parse_year(c["text"], now_year=FIX["now_year"])
    assert y == c["year"] and set(c["flags"]) <= set(flags)


@pytest.mark.parametrize(
    "raw,unit",
    [("Pieces", "pc"), ("件", "pc"), ("套", "set"), ("吨", "ton"), ("公斤", "kg"), ("قطعة", "pc"), ("طن", "ton"),
     ("كيلو", "kg"), ("متر", "m"), ("للطن", "ton"), ("per set", "set"), ("/ pair", "pair"), ("doz", "dozen"),
     ("m²", "m2"), ("㎡", "m2"), ("sq.m", "m2"), ("متر مربع", "m2"), ("立方米", "m3"), ("cbm", "m3"), ("litre", "liter"),
     ("كرتونة", "carton"), ("双", "pair"), ("xyz", None), ("", None)],
)
def test_normalize_unit(raw, unit):
    assert normalize_unit(raw) == unit


def test_convert_unit_price_exact_and_refuses_to_guess():
    D = Decimal
    assert convert_unit_price(D("450"), "ton", "kg") == D("0.45")
    assert convert_unit_price(D("2"), "kg", "ton") == D("2000")
    assert convert_unit_price(D("12"), "dozen", "pc") == D("1")
    assert convert_unit_price(D("95"), "m3", "liter") == D("0.095")
    assert convert_unit_price(D("5"), "kg", "kg") == D("5")
    for a, b in [("set", "pc"), ("carton", "pc"), ("pair", "pc"), ("kg", "m"), ("kg", "zzz")]:
        with pytest.raises(UnitConversionError):
            convert_unit_price(D(1), a, b)


def test_currency_yen_is_ambiguous_without_evidence():
    assert detect_currency_ex("¥5") == (None, ("CNY", "JPY"), ("ambiguous_currency_symbol",))
    assert detect_currency_ex("￥5")[0] is None  # full-width yen
    assert detect_currency_ex("¥5", "CN")[0] == "CNY" and detect_currency_ex("¥5", "jp")[0] == "JPY"
    assert detect_currency_ex("¥5 JPY")[0] == "JPY" and detect_currency_ex("5円")[0] == "JPY"
    assert detect_currency_ex("$5")[0] == "USD" and detect_currency_ex("US$5")[0] == "USD"
    assert detect_currency_ex("USDA grade") == (None, (), ())
    code, cands, flags = detect_currency_ex("$5 or €5")
    assert code is None and set(cands) == {"USD", "EUR"} and flags == ("ambiguous_currency_mixed",)


def test_parse_number_conventions():
    D = Decimal
    assert parse_number("1,234.50")[0] == D("1234.50") and parse_number("1.234,50")[0] == D("1234.50")
    assert parse_number("1,234")[0] == D("1234") and parse_number("12,5") == (D("12.5"), ("decimal_comma",))
    assert parse_number("12.500")[1] == ("ambiguous_number_separator",) and parse_number("0.125")[1] == ()


def test_parse_price_range_adapter_helper_uses_ladders_not_first_and_last_number():
    from ff_sourcing.adapters.http_provider import parse_price_range

    D = Decimal
    assert parse_price_range("US$10.00 (100-499 pieces); US$8.00 (500+ pieces)") == (D("8.00"), D("10.00"))
    assert parse_price_range("12,5 €") == (D("12.5"), D("12.5"))  # was 125 (comma silently dropped)
    assert parse_price_range("$5 12 pcs") is None  # was (5, 12)
