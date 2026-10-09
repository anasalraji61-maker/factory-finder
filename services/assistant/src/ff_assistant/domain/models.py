"""Shared shapes mirrored from ``contracts/schemas/common.schema.json`` (pure, no I/O).

Inbound models are tolerant (``extra="allow"``/``"ignore"``) so additive changes in other
services never break the assistant; money is always ``Decimal`` and serialized as a decimal
string.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer

_AMOUNT_RE = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")

Locale = Literal["ar", "en"]


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("amount must be a decimal string")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("amount must be finite")
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # Tolerated for robustness when another service sends a JSON number.
        return Decimal(repr(value))
    if isinstance(value, str):
        text = value.strip()
        if not _AMOUNT_RE.fullmatch(text):
            raise ValueError("amount must be a decimal string like '1234.50'")
        try:
            return Decimal(text)
        except InvalidOperation as exc:  # pragma: no cover - regex guards this
            raise ValueError("invalid decimal") from exc
    raise ValueError("amount must be a decimal string")


def decimal_to_str(value: Decimal) -> str:
    """Plain (non-exponent) decimal string; ``-0`` becomes ``0``."""
    text = format(value, "f")
    return "0" if text in {"-0", "-0.0"} else text


DecimalStr = Annotated[
    Decimal,
    BeforeValidator(_to_decimal),
    PlainSerializer(decimal_to_str, return_type=str, when_used="json"),
]

CountryCode = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class ListingKind(StrEnum):
    PRODUCT = "product"
    RAW_MATERIAL = "raw_material"
    PRODUCTION_LINE = "production_line"


class Condition(StrEnum):
    NEW = "new"
    USED = "used"
    REFURBISHED = "refurbished"


class TransportMode(StrEnum):
    SEA_LCL = "sea_lcl"
    SEA_FCL_20 = "sea_fcl_20"
    SEA_FCL_40 = "sea_fcl_40"
    SEA_FCL_40HC = "sea_fcl_40hc"
    AIR = "air"
    RAIL = "rail"
    ROAD = "road"


class Incoterm(StrEnum):
    EXW = "EXW"
    FCA = "FCA"
    FOB = "FOB"
    CFR = "CFR"
    CIF = "CIF"
    DAP = "DAP"
    DDP = "DDP"


class TrustBand(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    UNKNOWN = "unknown"


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _OpenModel(BaseModel):
    """Pass-through model: keeps optional fields added later by the owning service."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Money(_Model):
    amount: DecimalStr
    currency: CurrencyCode


class MoneyRange(_Model):
    min: Money
    max: Money


class DayRange(_Model):
    min: int = Field(ge=0)
    max: int = Field(ge=0)


class GeoPoint(_Model):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Location(_Model):
    country_code: CountryCode
    city: str | None = None
    point: GeoPoint | None = None


class SupplierSummary(_OpenModel):
    id: str
    name: str
    location: Location
    years_in_business: int | None = None
    verified: bool | None = None
    trust_score: int | None = Field(default=None, ge=0, le=100)
    trust_band: TrustBand | None = None


class Listing(_OpenModel):
    id: str
    source: str
    source_url: str | None = None
    kind: ListingKind
    condition: Condition | None = None
    title: str
    title_ar: str | None = None
    category: str | None = None
    images: list[str] | None = None
    price: MoneyRange
    unit: str | None = None
    moq: int | None = None
    incoterm: Incoterm | None = None
    unit_weight_kg: float | None = None
    unit_volume_m3: float | None = None
    hs_code: str | None = None
    lead_time_days: DayRange | None = None
    supplier: SupplierSummary
    origin: Location | None = None


class CostLine(_OpenModel):
    stage: str
    description: str
    amount: Money
    original_amount: Money | None = None
    fx_rate: str | None = None
    source: str | None = None
    estimate: bool


class LandedCostOption(_OpenModel):
    mode: TransportMode
    origin_hub: str | None = None
    destination_hub: str | None = None
    route_summary: str | None = None
    lines: list[CostLine]
    total: MoneyRange
    transit_days: DayRange
    co2_kg: float | None = None
    recommended: bool | None = None
    warnings: list[str] | None = None


class LandedCostQuote(_OpenModel):
    id: str
    currency: CurrencyCode
    origin: Location | None = None
    destination: Location | None = None
    options: list[LandedCostOption]
    assumptions: list[str] | None = None
    created_at: datetime


class TrustFactor(_OpenModel):
    key: str
    impact: int
    explanation: str
    explanation_ar: str | None = None


class TrustScore(_OpenModel):
    supplier_id: str
    score: int = Field(ge=0, le=100)
    band: TrustBand
    factors: list[TrustFactor]
    computed_at: datetime | None = None


def band_for_score(score: int) -> TrustBand:
    """Fallback band when only a numeric score is known (trust owns the real thresholds)."""
    if score >= 75:
        return TrustBand.GREEN
    if score >= 50:
        return TrustBand.YELLOW
    return TrustBand.RED
