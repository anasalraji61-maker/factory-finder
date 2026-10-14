"""Supplier-owned ("native") listing input validation + sanitising. Pure: no I/O."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .categories import CATEGORY_TREE
from .models import Condition, ListingKind

STATUSES = ("draft", "published", "archived")
INCOTERMS = ("EXW", "FCA", "FOB", "CFR", "CIF", "DAP", "DDP")
MAX_IMAGES = 8
MAX_AMOUNT = Decimal("1000000000")  # 1e9 per unit
MAX_DECIMALS = 6

# category leaf slug -> its listing kind (a listing's category must belong to its kind)
LEAF_KIND: dict[str, str] = {c.slug: top.slug for top in CATEGORY_TREE for c in top.children}

_BIDI = dict.fromkeys(
    [*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0xFEFF, 0x200E, 0x200F, 0x061C], None
)


def clean_text(value: Any, *, multiline: bool = False) -> Any:
    """Strip control chars + bidi overrides, normalise unicode (NFC) and surrounding whitespace."""
    if not isinstance(value, str):
        return value
    v = unicodedata.normalize("NFC", value).translate(_BIDI)
    keep = "\n\t" if multiline else ""
    v = "".join(ch for ch in v if ch in keep or unicodedata.category(ch) not in ("Cc", "Cs", "Co"))
    if multiline:
        v = re.sub(r"[ \t]+\n", "\n", v)
        v = re.sub(r"\n{3,}", "\n\n", v)
    else:
        v = re.sub(r"\s+", " ", v)
    return v.strip()


def _line(v: Any) -> Any:
    return clean_text(v)


def _multi(v: Any) -> Any:
    return clean_text(v, multiline=True)


Line = Annotated[str, BeforeValidator(_line)]
Multi = Annotated[str, BeforeValidator(_multi)]


class MoneyIn(BaseModel):
    amount: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("amount")
    @classmethod
    def _amount(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[0-9]+(\.[0-9]+)?", v):
            raise ValueError("amount must be a plain decimal string like '12.50'")
        try:
            d = Decimal(v)
        except InvalidOperation as e:  # pragma: no cover - regex already guards
            raise ValueError("invalid amount") from e
        if d <= 0:
            raise ValueError("amount must be > 0")
        if d > MAX_AMOUNT:
            raise ValueError("amount too large")
        if -d.as_tuple().exponent > MAX_DECIMALS:  # type: ignore[operator]
            raise ValueError(f"at most {MAX_DECIMALS} decimal places")
        return v


class MoneyRangeIn(BaseModel):
    min: MoneyIn
    max: MoneyIn

    @model_validator(mode="after")
    def _check(self) -> MoneyRangeIn:
        if self.min.currency != self.max.currency:
            raise ValueError("min and max must use the same currency")
        if Decimal(self.min.amount) > Decimal(self.max.amount):
            raise ValueError("price.min must be <= price.max")
        return self


class DayRangeIn(BaseModel):
    min: int = Field(ge=0, le=730)
    max: int = Field(ge=0, le=730)

    @model_validator(mode="after")
    def _check(self) -> DayRangeIn:
        if self.min > self.max:
            raise ValueError("lead_time_days.min must be <= max")
        return self


class GeoPointIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class LocationIn(BaseModel):
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    city: Annotated[Line, Field(min_length=1, max_length=80)] | None = None
    point: GeoPointIn | None = None


def _http_url(v: Any) -> Any:
    if not isinstance(v, str):
        return v
    v = v.strip()
    if len(v) > 2048 or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in v):
        raise ValueError("invalid url")
    parts = urlsplit(v)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username:
        raise ValueError("images must be http(s) URLs")
    return v


ImageUrl = Annotated[str, BeforeValidator(_http_url)]


class ListingWrite(BaseModel):
    """Body of POST/PUT /v1/my/listings. Unknown fields (incl. supplier/source/status/id) are ignored."""

    model_config = ConfigDict(extra="ignore")

    kind: ListingKind
    condition: Condition = "new"
    title: Annotated[Line, Field(min_length=3, max_length=140)]
    title_ar: Annotated[Line, Field(min_length=3, max_length=140)] | None = None
    description: Annotated[Multi, Field(max_length=4000)] | None = None
    description_ar: Annotated[Multi, Field(max_length=4000)] | None = None
    category: Annotated[str, Field(max_length=64)]
    price: MoneyRangeIn
    unit: Annotated[Line, Field(min_length=1, max_length=24)]
    moq: int = Field(default=1, ge=1, le=1_000_000_000)
    incoterm: str | None = None
    unit_weight_kg: float | None = Field(default=None, gt=0, le=1_000_000, allow_inf_nan=False)
    unit_volume_m3: float | None = Field(default=None, gt=0, le=100_000, allow_inf_nan=False)
    hs_code: str | None = Field(default=None, pattern=r"^[0-9]{6,10}$")
    lead_time_days: DayRangeIn | None = None
    images: list[ImageUrl] = Field(default_factory=list, max_length=MAX_IMAGES)
    origin: LocationIn
    specs: dict[Annotated[Line, Field(min_length=1, max_length=60)], Annotated[Line, Field(max_length=200)]] = (
        Field(default_factory=dict, max_length=20)
    )

    @field_validator("incoterm")
    @classmethod
    def _incoterm(cls, v: str | None) -> str | None:
        if v is not None and v not in INCOTERMS:
            raise ValueError(f"incoterm must be one of {', '.join(INCOTERMS)}")
        return v

    @model_validator(mode="after")
    def _category(self) -> ListingWrite:
        if LEAF_KIND.get(self.category) != self.kind:
            raise ValueError("category must be a leaf slug from /v1/categories that belongs to kind")
        return self
