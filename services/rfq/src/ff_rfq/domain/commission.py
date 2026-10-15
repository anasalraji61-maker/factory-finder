"""Commission on an accepted offer: percentage by listing kind with a minimum fee (USD)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from ff_rfq.domain.enums import ListingKind
from ff_rfq.domain.errors import UnsupportedCurrency

CENT = Decimal("0.01")
# Minor-unit exponent per currency; absent = 2. IQD/JPY are handled as whole units (no fractional dinars/yen).
ZERO_DECIMAL = frozenset({"IQD", "JPY"})


def money_quantum(currency: str) -> Decimal:
    return Decimal("1") if currency in ZERO_DECIMAL else CENT


def quantize_money(value: Decimal, currency: str) -> Decimal:
    """Round half-up to the currency's minor unit."""
    return value.quantize(money_quantum(currency), rounding=ROUND_HALF_UP)

DEFAULT_RATES: dict[ListingKind, Decimal] = {
    ListingKind.PRODUCT: Decimal("0.03"),
    ListingKind.RAW_MATERIAL: Decimal("0.02"),
    ListingKind.PRODUCTION_LINE: Decimal("0.04"),
}
# Static reference rates (1 unit of currency in USD) used only for the minimum-fee floor; estimate.
DEFAULT_USD_RATES: dict[str, Decimal] = {
    "USD": Decimal("1"), "EUR": Decimal("1.08"), "GBP": Decimal("1.27"), "CNY": Decimal("0.14"),
    "AED": Decimal("0.2723"), "TRY": Decimal("0.03"), "IQD": Decimal("0.00076"),
    "SAR": Decimal("0.2667"), "JPY": Decimal("0.0067"), "INR": Decimal("0.012"),
}


@dataclass(frozen=True, slots=True)
class Commission:
    rate: Decimal
    amount: Decimal
    currency: str
    min_fee_applied: bool


def compute_commission(
    subtotal: Decimal, currency: str, kind: ListingKind, *,
    rates: dict[ListingKind, Decimal] = DEFAULT_RATES,
    min_fee_usd: Decimal = Decimal("25"),
    usd_rates: dict[str, Decimal] = DEFAULT_USD_RATES,
) -> Commission:
    if currency not in usd_rates:
        raise UnsupportedCurrency(f"Currency {currency} is not supported", details={"currency": currency})
    rate = rates[kind]
    quantum = money_quantum(currency)
    pct = (subtotal * rate).quantize(quantum, rounding=ROUND_HALF_UP)
    floor = (min_fee_usd / usd_rates[currency]).quantize(quantum, rounding=ROUND_CEILING)
    if pct < floor:
        return Commission(rate, floor, currency, True)
    return Commission(rate, pct, currency, False)
