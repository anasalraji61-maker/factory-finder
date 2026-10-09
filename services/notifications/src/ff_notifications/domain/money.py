"""Exact money values and percentage maths.

Amounts are always :class:`decimal.Decimal` and travel through JSON as decimal strings
(``{"amount": "1234.50", "currency": "USD"}``). Floats are never accepted for money.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

AMOUNT_PATTERN = r"^-?[0-9]+(\.[0-9]+)?$"
CURRENCY_PATTERN = r"^[A-Z]{3}$"

_AMOUNT_RE = re.compile(AMOUNT_PATTERN)
_CURRENCY_RE = re.compile(CURRENCY_PATTERN)
_HUNDRED = Decimal(100)
_CENT = Decimal("0.01")
_MAX_DISPLAY_PLACES = 6


class MoneyError(ValueError):
    """An amount or currency is not valid."""


class CurrencyMismatchError(MoneyError):
    """Two amounts in different currencies were compared or combined."""


def parse_amount(value: object) -> Decimal:
    """Parse an exact decimal amount.

    Accepts ``Decimal``, ``int`` and decimal strings such as ``"1234.50"``. Floats (and
    bools) are rejected because they cannot represent most decimal amounts exactly.
    """
    if isinstance(value, bool):
        raise MoneyError("amount must be a decimal string")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise MoneyError("amount must be finite")
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        text = value.strip()
        if not _AMOUNT_RE.fullmatch(text):
            raise MoneyError(f"invalid decimal amount: {value!r}")
        return Decimal(text)
    raise MoneyError(f"unsupported amount type: {type(value).__name__}")


def format_amount(value: Decimal) -> str:
    """Render a Decimal as a plain decimal string (never scientific notation)."""
    return format(value, "f")


def canonical_amount(value: Decimal) -> str:
    """Stable textual form that ignores trailing zeros (``100.00`` -> ``100``)."""
    return format_amount(value.normalize()) if value != 0 else "0"


def is_valid_currency(code: object) -> bool:
    return isinstance(code, str) and bool(_CURRENCY_RE.fullmatch(code))


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount in an ISO-4217 currency."""

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise MoneyError("amount must be a finite Decimal")
        if not is_valid_currency(self.currency):
            raise MoneyError(f"invalid currency code: {self.currency!r}")

    @classmethod
    def of(cls, amount: object, currency: str) -> Money:
        return cls(parse_amount(amount), currency)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Money:
        try:
            return cls.of(data["amount"], data["currency"])
        except (KeyError, TypeError) as exc:
            raise MoneyError("money must be an object with amount and currency") from exc

    def to_json(self) -> dict[str, str]:
        return {"amount": format_amount(self.amount), "currency": self.currency}

    def same_currency(self, other: Money) -> bool:
        return self.currency == other.currency

    def _require_same_currency(self, other: Money) -> None:
        if not self.same_currency(other):
            raise CurrencyMismatchError(f"cannot compare {self.currency} with {other.currency}")

    def __lt__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._require_same_currency(other)
        return self.amount >= other.amount

    def format(self) -> str:
        """Human text such as ``1,234.50 USD`` (keeps sub-cent precision when present)."""
        exponent = self.amount.normalize().as_tuple().exponent
        places = 2
        if isinstance(exponent, int) and exponent < -2:
            places = min(-exponent, _MAX_DISPLAY_PLACES)
        quantum = Decimal(1).scaleb(-places)
        rounded = self.amount.quantize(quantum, rounding=ROUND_HALF_UP)
        return f"{rounded:,.{places}f} {self.currency}"


def dropped_at_least(old: Decimal, new: Decimal, percent: Decimal) -> bool:
    """Exact check that ``new`` is at least ``percent`` % below ``old`` (no rounding)."""
    if old <= 0:
        return False
    return (old - new) * _HUNDRED >= percent * old


def drop_percent(old: Decimal, new: Decimal) -> Decimal:
    """Percentage fall from ``old`` to ``new`` (positive = cheaper), rounded half-up to 0.01."""
    if old <= 0:
        raise MoneyError("reference amount must be positive")
    return ((old - new) * _HUNDRED / old).quantize(_CENT, rounding=ROUND_HALF_UP)


def format_percent(value: Decimal) -> str:
    """``12.50`` -> ``12.5``, ``12.04`` -> ``12``: one decimal at most, no trailing zero."""
    rounded = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if rounded == rounded.to_integral_value():
        return format_amount(rounded.to_integral_value())
    return format_amount(rounded)
