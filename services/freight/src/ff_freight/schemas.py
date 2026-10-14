"""Request bodies (extra fields are rejected) and shared patterns."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ff_freight.moderation import REPORT_REASONS

USER_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")
ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
REF_RE = r"^[A-Za-z0-9_.:\-]{1,64}$"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HS = re.compile(r"^\d{4,10}$")
_CERT = re.compile(r"^[\w .&/+\-]{2,40}$")

MODES = ("sea", "air", "road", "rail")
INCOTERMS = ("EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP")
CONTAINER_TYPES = ("20GP", "40GP", "40HC", "45HC", "20RF", "40RF", "20OT", "40OT", "20FR", "40FR", "LCL")
CONTAINER_MODES = ("sea", "rail")  # container types only make sense on these modes
REQUEST_STATUSES = ("open", "awarded", "closed", "expired")
SORTS = ("score", "price", "transit", "rating")

Mode = Literal["sea", "air", "road", "rail"]
Incoterm = Literal["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"]
Country = Annotated[str, Field(pattern=r"^[A-Z]{2}$")]
LaneCountry = Annotated[str, Field(pattern=r"^([A-Z]{2}|\*)$")]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
Money = Annotated[Decimal, Field(gt=0, lt=Decimal("1000000000"), max_digits=12, decimal_places=2)]
Weight = Annotated[Decimal, Field(gt=0, le=Decimal("10000000"), max_digits=11, decimal_places=3)]

MAX_LANES = 50


def clean(v: str) -> str:
    v = v.strip()
    if _CONTROL.search(v):
        raise ValueError("control characters are not allowed")
    return v


def csv_key(items: list[str]) -> str:
    """Stable ',a,b,' key used for LIKE filtering."""
    return "," + ",".join(items) + ","


def csv_list(key: str) -> list[str]:
    return [x for x in key.split(",") if x]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Lane(_Body):
    origin_country: LaneCountry
    destination_country: LaneCountry


def _dedupe(seq):
    out = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


class _ProfileFields(_Body):
    @staticmethod
    def _lanes(v: list[Lane]) -> list[Lane]:
        out = _dedupe([(x.origin_country, x.destination_country) for x in v])
        return [Lane(origin_country=o, destination_country=d) for o, d in out]

    @staticmethod
    def _certs(v: list[str]) -> list[str]:
        out = []
        for raw in v:
            c = clean(raw)
            if not _CERT.match(c):
                raise ValueError("certification labels are 2-40 characters (letters, digits, space . & / + -)")
            if c not in out:
                out.append(c)
        return out


class ApplicationCreate(_ProfileFields):
    company_name: Annotated[str, Field(min_length=2, max_length=120)]
    country_code: Country
    description: Annotated[str | None, Field(max_length=1000)] = None
    lanes: Annotated[list[Lane], Field(min_length=1, max_length=MAX_LANES)]
    modes: Annotated[list[Mode], Field(min_length=1, max_length=4)]
    incoterms: Annotated[list[Incoterm], Field(min_length=1, max_length=11)]
    certifications: Annotated[list[Annotated[str, Field(max_length=60)]], Field(max_length=10)] = []

    @field_validator("company_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = clean(v)
        if len(v) < 2:
            raise ValueError("company_name too short")
        return v

    @field_validator("description")
    @classmethod
    def _desc(cls, v: str | None) -> str | None:
        return clean(v) or None if v else None

    @field_validator("lanes")
    @classmethod
    def _l(cls, v):
        return cls._lanes(v)

    @field_validator("modes", "incoterms")
    @classmethod
    def _uniq(cls, v):
        return _dedupe(v)

    @field_validator("certifications")
    @classmethod
    def _c(cls, v):
        return cls._certs(v)


class ProfileUpdate(_ProfileFields):
    """Forwarder-editable profile fields (company name and country change only via admin)."""

    description: Annotated[str | None, Field(max_length=1000)] = None
    lanes: Annotated[list[Lane] | None, Field(min_length=1, max_length=MAX_LANES)] = None
    modes: Annotated[list[Mode] | None, Field(min_length=1, max_length=4)] = None
    incoterms: Annotated[list[Incoterm] | None, Field(min_length=1, max_length=11)] = None
    certifications: Annotated[list[Annotated[str, Field(max_length=60)]] | None, Field(max_length=10)] = None

    @field_validator("description")
    @classmethod
    def _desc(cls, v: str | None) -> str | None:
        return clean(v) or None if v else None

    @field_validator("lanes")
    @classmethod
    def _l(cls, v):
        return None if v is None else cls._lanes(v)

    @field_validator("modes", "incoterms")
    @classmethod
    def _uniq(cls, v):
        return None if v is None else _dedupe(v)

    @field_validator("certifications")
    @classmethod
    def _c(cls, v):
        return None if v is None else cls._certs(v)


class RequestCreate(_Body):
    origin_country: Country
    origin_place: Annotated[str, Field(min_length=2, max_length=80)]
    destination_country: Country
    destination_place: Annotated[str, Field(min_length=2, max_length=80)]
    cargo_description: Annotated[str, Field(min_length=3, max_length=500)]
    hs_code: str | None = None
    weight_kg: Weight | None = None
    volume_cbm: Weight | None = None
    mode: Mode
    container_type: Literal["20GP", "40GP", "40HC", "45HC", "20RF", "40RF", "20OT", "40OT", "20FR", "40FR", "LCL"] | None = None
    container_count: Annotated[int | None, Field(ge=1, le=500)] = None
    incoterm: Incoterm
    ready_date: str  # ISO date; checked against the clock in the service
    currency: Currency = "USD"
    quote_deadline_days: Annotated[int, Field(ge=1, le=30)] = 14
    landed_cost_ref: Annotated[str | None, Field(pattern=REF_RE)] = None

    @field_validator("origin_place", "destination_place", "cargo_description")
    @classmethod
    def _txt(cls, v: str) -> str:
        v = clean(v)
        if len(v) < 2:
            raise ValueError("too short")
        return v

    @field_validator("hs_code")
    @classmethod
    def _hs(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().replace(".", "").replace(" ", "")
        if not _HS.match(v):
            raise ValueError("hs_code must be 4-10 digits")
        return v

    @model_validator(mode="after")
    def _shape(self):
        if self.weight_kg is None and self.volume_cbm is None:
            raise ValueError("weight_kg or volume_cbm is required")
        if self.container_type and self.mode not in CONTAINER_MODES:
            raise ValueError("container_type applies to sea and rail shipments only")
        if self.container_count and not self.container_type:
            raise ValueError("container_count needs container_type")
        return self


class QuoteLine(_Body):
    label: Annotated[str, Field(min_length=2, max_length=60)]
    amount: Money

    @field_validator("label")
    @classmethod
    def _label(cls, v: str) -> str:
        v = clean(v)
        if len(v) < 2:
            raise ValueError("label too short")
        return v


def _items(v: list[str]) -> list[str]:
    out = []
    for raw in v:
        s = clean(raw)
        if not s:
            raise ValueError("empty item")
        if s not in out:
            out.append(s)
    return out


class QuoteCreate(_Body):
    amount: Money
    currency: Currency
    transit_days: Annotated[int, Field(ge=1, le=365)]
    valid_days: Annotated[int, Field(ge=1, le=90)] = 14
    inclusions: Annotated[list[Annotated[str, Field(min_length=2, max_length=80)]], Field(max_length=10)] = []
    exclusions: Annotated[list[Annotated[str, Field(min_length=2, max_length=80)]], Field(max_length=10)] = []
    breakdown: Annotated[list[QuoteLine], Field(max_length=10)] = []
    terms: Annotated[str | None, Field(max_length=1000)] = None

    @field_validator("inclusions", "exclusions")
    @classmethod
    def _i(cls, v):
        return _items(v)

    @field_validator("terms")
    @classmethod
    def _t(cls, v: str | None) -> str | None:
        return clean(v) or None if v else None


class AcceptIn(_Body):
    """Optional guard against bait-and-switch: the revision the buyer saw. A forwarder revising the quote
    between the buyer's comparison and the accept makes the accept fail with 409 `quote_changed`."""

    revision: Annotated[int | None, Field(ge=1, le=1_000_000)] = None


class RatingIn(_Body):
    stars: Annotated[int, Field(ge=1, le=5)]
    comment: Annotated[str | None, Field(max_length=500)] = None

    @field_validator("comment")
    @classmethod
    def _c(cls, v: str | None) -> str | None:
        return clean(v) or None if v else None


class ReportIn(_Body):
    reason: Literal[REPORT_REASONS]  # type: ignore[valid-type]
    details: Annotated[str | None, Field(max_length=300)] = None


class ReasonIn(_Body):
    reason: Annotated[str, Field(min_length=3, max_length=300)]

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = clean(v)
        if len(v) < 3:
            raise ValueError("reason too short")
        return v


class NoteIn(_Body):
    note: Annotated[str | None, Field(max_length=300)] = None

    @field_validator("note")
    @classmethod
    def _n(cls, v: str | None) -> str | None:
        return clean(v) or None if v else None
