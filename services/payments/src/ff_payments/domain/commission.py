"""Platform commission (mirrors services/rfq: product 3%, raw material 2%, production line 4%, min 25 USD).

Half-up to cents; the minimum is converted with static reference rates (an estimate) and rounded up.
Duplicated on purpose: modules never import each other's internals (CLAUDE.md rule 1).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from ff_payments.domain.enums import ListingKind
from ff_payments.domain.errors import ValidationFailed

CENT = Decimal("0.01")
DEFAULT_RATES: dict[ListingKind, Decimal] = {
    ListingKind.PRODUCT: Decimal("0.03"),
    ListingKind.RAW_MATERIAL: Decimal("0.02"),
    ListingKind.PRODUCTION_LINE: Decimal("0.04"),
}
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
        raise ValidationFailed(f"Currency {currency} is not supported", code="unsupported_currency",
                               details={"currency": currency})
    rate = rates[kind]
    pct = (subtotal * rate).quantize(CENT, rounding=ROUND_HALF_UP)
    floor = (min_fee_usd / usd_rates[currency]).quantize(CENT, rounding=ROUND_CEILING)
    if pct < floor:
        return Commission(rate, floor, currency, True)
    return Commission(rate, pct, currency, False)
