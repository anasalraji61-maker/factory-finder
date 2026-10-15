"""Exact money helpers: Decimal only, half-up rounding, per-currency minor units. Floats are rejected."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

# Project convention (matches logistics): IQD is treated as zero-decimal in practice.
_EXP: dict[str, int] = {
    "JPY": 0, "KRW": 0, "VND": 0, "IQD": 0, "IRR": 0, "CLP": 0, "ISK": 0, "UGX": 0, "XOF": 0, "XAF": 0,
    "KWD": 3, "BHD": 3, "OMR": 3, "JOD": 3, "TND": 3, "LYD": 3,
}  # fmt: skip


def minor_exponent(currency: str) -> int:
    return _EXP.get(currency.upper(), 2)


def to_decimal(value: object) -> Decimal:
    """Parse str/int/Decimal to a finite Decimal. Floats and bools are rejected (inexact)."""
    if isinstance(value, (bool, float)):
        raise TypeError("float/bool not allowed for money; pass str, int or Decimal")
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    elif isinstance(value, str):
        try:
            d = Decimal(value.strip().replace(",", ""))
        except InvalidOperation as e:
            raise ValueError(f"invalid amount: {value!r}") from e
    else:
        raise TypeError(f"unsupported amount type: {type(value).__name__}")
    if not d.is_finite():
        raise ValueError("amount must be finite")
    return d


def quantize(value: object, currency: str) -> Decimal:
    """Round half-up (away from zero on ties, incl. negatives) to the currency's minor unit."""
    d = to_decimal(value)
    exp = Decimal(1).scaleb(-minor_exponent(currency))
    with localcontext() as ctx:
        ctx.prec = max(ctx.prec, len(d.as_tuple().digits) + abs(d.as_tuple().exponent) + 10)
        return d.quantize(exp, rounding=ROUND_HALF_UP)


def to_minor(value: object, currency: str) -> int:
    sign, digits, exp = quantize(value, currency).as_tuple()
    n = int("".join(map(str, digits)) or "0") * 10 ** (exp + minor_exponent(currency))  # exp >= -minor exp
    return -n if sign else n


def from_minor(units: int, currency: str) -> Decimal:
    if isinstance(units, bool) or not isinstance(units, int):
        raise TypeError("minor units must be int")
    with localcontext() as ctx:
        ctx.prec = max(ctx.prec, len(str(abs(units))) + 5)  # default 28 digits would round huge values
        return Decimal(units).scaleb(-minor_exponent(currency))


def money(value: object, currency: str) -> dict[str, str]:
    """Wire form: amount as a plain decimal string (never scientific notation)."""
    return {"amount": format(quantize(value, currency), "f"), "currency": currency.upper()}
