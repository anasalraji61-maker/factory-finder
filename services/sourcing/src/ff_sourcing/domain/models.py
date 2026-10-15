from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

ListingKind = Literal["product", "raw_material", "production_line"]
Condition = Literal["new", "used", "refurbished"]
TrustBand = Literal["green", "yellow", "red", "unknown"]


class Money(BaseModel):
    amount: Decimal
    currency: str


class MoneyRange(BaseModel):
    min: Money
    max: Money


class DayRange(BaseModel):
    min: int
    max: int


class GeoPoint(BaseModel):
    lat: float
    lon: float


class Location(BaseModel):
    country_code: str
    city: str | None = None
    point: GeoPoint | None = None


class SupplierSummary(BaseModel):
    id: str
    name: str
    name_ar: str | None = None
    location: Location
    years_in_business: int | None = None
    verified: bool = False
    trust_score: int | None = Field(default=None, ge=0, le=100)
    trust_band: TrustBand = "unknown"


class Supplier(SupplierSummary):
    certifications: list[str] = []
    listing_count: int = 0
    source: str = "mock"


class Listing(BaseModel):
    id: str
    source: str
    source_url: str | None = None
    kind: ListingKind
    condition: Condition = "new"
    title: str
    title_ar: str | None = None
    category: str | None = None
    images: list[str] = []
    price: MoneyRange
    unit: str | None = None
    moq: int | None = None
    incoterm: str | None = None
    unit_weight_kg: float | None = None
    unit_volume_m3: float | None = None
    hs_code: str | None = None
    lead_time_days: DayRange | None = None
    supplier: SupplierSummary
    origin: Location | None = None


class ListingDetail(Listing):
    description: str | None = None
    description_ar: str | None = None
    specs: dict[str, str] = {}


class SearchQuery(BaseModel):
    """Structured query handed to adapters. Keyword matching/ranking is done by the engine."""

    q: str = ""
    kind: ListingKind | None = None
    condition: Literal["new", "used", "refurbished", "any"] = "any"
    origin_country: str | None = None
    category: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    moq_max: int | None = None
    verified_only: bool = False
    # English keywords for remote APIs (filled by the engine from synonyms)
    keywords_en: list[str] = []
    limit: int = 200


class SourceStatus(BaseModel):
    source: str
    status: Literal["ok", "timeout", "error"]
    count: int = 0
    warning: str | None = None  # e.g. real source failed and mock results were substituted


class FacetBucket(BaseModel):
    value: str
    count: int


class Facets(BaseModel):
    """Counts over the full matched set (all pages), each sorted by count desc then value."""

    kind: list[FacetBucket] = []
    condition: list[FacetBucket] = []
    origin_country: list[FacetBucket] = []
    category: list[FacetBucket] = []


class SearchResponse(BaseModel):
    items: list[Listing]
    total: int
    page: int
    page_size: int
    sources: list[SourceStatus]
    facets: Facets = Facets()
    warning: str | None = None  # additive: partial_results when a source failed/timed out or mock was substituted


class CategoryNode(BaseModel):
    slug: str
    name: str
    name_ar: str
    children: list[CategoryNode] = []
