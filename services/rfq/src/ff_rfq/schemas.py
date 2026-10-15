"""Request-body models (responses are plain dicts built by the service)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from ff_rfq.domain.enums import Incoterm, ListingKind, RequestCondition, Visibility
from ff_rfq.domain.review_text import sanitize


def _clean(v: object, multiline: bool) -> object:
    """Strip control / bidi / zero-width characters from free text (runs before length constraints)."""
    if not isinstance(v, str):
        return v
    out = sanitize(v)
    return out if multiline else " ".join(out.split())


class Money(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=4)]
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_serializer("amount")
    def _amount(self, v: Decimal) -> str:
        return format(v, "f")


class Destination(BaseModel):
    model_config = ConfigDict(extra="forbid")
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    city: str | None = Field(default=None, max_length=100)

    @field_validator("city", mode="before")
    @classmethod
    def _city(cls, v: object) -> object:
        return _clean(v, False)


class RequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ListingKind
    title: str = Field(min_length=3, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    quantity: Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=4)]
    unit: str = Field(default="piece", min_length=1, max_length=24)
    condition: RequestCondition = RequestCondition.ANY
    target_price: Money | None = Field(default=None, description="Per unit")
    destination: Destination | None = None
    deadline: datetime | None = None
    attachments: list[str] = Field(default_factory=list, max_length=10)
    visibility: Visibility = Visibility.PUBLIC


    @field_validator("title", "unit", mode="before")
    @classmethod
    def _single_line(cls, v: object) -> object:
        return _clean(v, False)

    @field_validator("description", mode="before")
    @classmethod
    def _multi_line(cls, v: object) -> object:
        return _clean(v, True)

    @field_validator("attachments", mode="before")
    @classmethod
    def _attachments(cls, v: object) -> object:
        return [_clean(x, False) for x in v] if isinstance(v, list) else v


class OfferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price: Money = Field(description="Per unit")
    supplier_name: str = Field(min_length=1, max_length=200)
    supplier_ref: str | None = Field(default=None, max_length=64, description="Deprecated and ignored: identity comes from the verified X-Supplier-Id header")
    moq: int | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0, le=1000)
    incoterm: Incoterm | None = None
    valid_until: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("supplier_name", mode="before")
    @classmethod
    def _name(cls, v: object) -> object:
        return _clean(v, False)

    @field_validator("notes", mode="before")
    @classmethod
    def _notes(cls, v: object) -> object:
        return _clean(v, True)


Stars = Annotated[int, Field(ge=1, le=5, strict=True)]


class SubRatings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quality: Stars | None = None
    communication: Stars | None = None
    shipping: Stars | None = None


class ReviewCreate(BaseModel):
    """Used for both POST and PUT (PUT replaces the editable fields)."""

    model_config = ConfigDict(extra="forbid")
    rating: Stars
    title: str | None = Field(default=None, max_length=80)
    text: str | None = Field(default=None, max_length=1000)
    sub_ratings: SubRatings | None = None


class ReplyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="other", pattern="^(spam|abuse|fake|other)$")
    note: str | None = Field(default=None, max_length=300)


class PaymentStatusCallback(BaseModel):
    """Internal (payments -> rfq). ``event_id`` makes redelivery idempotent."""

    model_config = ConfigDict(extra="forbid")
    invoice_id: str = Field(min_length=1, max_length=64)
    kind: Literal["commission", "deal_payment"]
    status: Literal["paid", "refunded"]
    amount: Money
    event_id: str = Field(min_length=1, max_length=128)
    # other invoice kinds of this deal that are still open (pending/awaiting/confirming) at event time
    other_open_kinds: list[Literal["commission", "deal_payment"]] = Field(default_factory=list, max_length=2)
