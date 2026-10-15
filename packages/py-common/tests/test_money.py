from decimal import Decimal

import pytest

from ff_common.money import from_minor, minor_exponent, money, quantize, to_decimal, to_minor


@pytest.mark.parametrize("cur,exp", [("USD", 2), ("JPY", 0), ("IQD", 0), ("KWD", 3), ("kwd", 3), ("XXX", 2)])
def test_exponent(cur, exp):
    assert minor_exponent(cur) == exp


@pytest.mark.parametrize("val,cur,out", [
    ("1.005", "USD", "1.01"), ("1.004", "USD", "1.00"), ("2.5", "JPY", "3"), ("1234.5", "IQD", "1235"),
    ("1.0005", "KWD", "1.001"), ("1.0004", "KWD", "1.000"), (7, "USD", "7.00"),
])  # fmt: skip
def test_half_up(val, cur, out):
    assert str(quantize(val, cur)) == out


def test_negative_ties_round_away_from_zero():
    assert str(quantize("-1.005", "USD")) == "-1.01"
    assert str(quantize("-2.5", "JPY")) == "-3"
    assert str(quantize("-0.0004", "KWD")) == "0.000" or str(quantize("-0.0004", "KWD")) == "-0.000"


def test_float_and_bool_rejected():
    for bad in (1.1, True, None, [1]):
        with pytest.raises(TypeError):
            to_decimal(bad)


def test_bad_strings():
    for bad in ("abc", "", "NaN", "Infinity", "-inf"):
        with pytest.raises(ValueError):
            to_decimal(bad)


def test_thousands_separator_and_whitespace():
    assert to_decimal(" 1,234.50 ") == Decimal("1234.50")


def test_huge_values_exact():
    big = "123456789012345678901234567890.125"
    assert str(quantize(big, "USD")) == "123456789012345678901234567890.13"
    assert to_minor(big, "USD") == 12345678901234567890123456789013
    assert money("1E+30", "USD")["amount"] == "1000000000000000000000000000000.00"


def test_minor_roundtrip():
    for cur, v in [("USD", "19.99"), ("JPY", "1500"), ("KWD", "3.141"), ("IQD", "250000")]:
        assert from_minor(to_minor(v, cur), cur) == Decimal(v)
    with pytest.raises(TypeError):
        from_minor(1.5, "USD")  # type: ignore[arg-type]


def test_money_wire_form_never_scientific():
    assert money("0.0000001", "USD") == {"amount": "0.00", "currency": "USD"}
    assert money("5", "kwd") == {"amount": "5.000", "currency": "KWD"}
    assert money(Decimal("1E+3"), "JPY")["amount"] == "1000"


def test_huge_minor_roundtrip_and_negative():
    big = 10**40 + 7
    assert from_minor(big, "USD") == Decimal("1" + "0" * 38 + ".07")
    assert to_minor(from_minor(-big, "KWD"), "KWD") == -big
    assert to_minor("-1.005", "USD") == -101
