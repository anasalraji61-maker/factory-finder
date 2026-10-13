"""Helpers shared by real-adapter normalizers."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from ..domain.models import (
    ListingDetail,
    Location,
    Money,
    MoneyRange,
    SupplierSummary,
)


def dec(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return Decimal(default)


def build_listing(
    *,
    source: str,
    native_id: str,
    title: str,
    price_min: Any,
    price_max: Any,
    currency: str,
    supplier_native_id: str,
    supplier_name: str,
    country: str = "CN",
    city: str | None = None,
    kind: str = "product",
    url: str | None = None,
    images: list[str] | None = None,
    moq: int | None = None,
    unit: str | None = None,
    verified: bool = False,
) -> ListingDetail:
    lo, hi = dec(price_min), dec(price_max if price_max not in (None, "") else price_min)
    if hi < lo:
        lo, hi = hi, lo
    loc = Location(country_code=country, city=city)
    return ListingDetail(
        id=f"lst_{source}_{native_id}",
        source=source,
        source_url=url,
        kind=kind,  # type: ignore[arg-type]
        title=title,
        images=images or [],
        unit=unit,
        moq=moq,
        price=MoneyRange(
            min=Money(amount=lo, currency=currency), max=Money(amount=hi, currency=currency)
        ),
        supplier=SupplierSummary(
            id=f"sup_{source}_{supplier_native_id}",
            name=supplier_name,
            location=loc,
            verified=verified,
        ),
        origin=loc,
    )
