"""Input signals about a supplier. Every field is optional; missing means "unknown"."""

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ff_trust.domain.verification import VerificationEvidence

LicenseStatus = Literal["verified", "pending", "unverified", "expired", "mismatch"]


class CertificationRecord(BaseModel):
    """A certificate with optional expiry (expired ones stop counting)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    expires_on: date | None = None


class ReviewSummary(BaseModel):
    """Verified-purchase review aggregates from rfq (`rfq.yaml#ReviewSummary`). Optional input signal."""

    model_config = ConfigDict(extra="ignore")

    count: int = Field(default=0, ge=0)
    average: float | None = Field(default=None, ge=0, le=5)
    histogram: dict[str, int] | None = None  # keys "1".."5"
    sub_ratings: dict[str, float | None] | None = None  # quality / communication / shipping
    completed_deals: int | None = Field(default=None, ge=0)
    first_review_at: datetime | None = None  # optional review timestamps (rfq created_at/updated_at of oldest/newest)
    last_review_at: datetime | None = None


class SupplierSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: str | None = Field(default=None, max_length=128)
    years_in_business: float | None = Field(default=None, ge=0, le=200)
    verified: bool | None = None
    third_party_audit: bool | None = None
    transactions_count: int | None = Field(default=None, ge=0)
    response_rate: float | None = Field(default=None, ge=0, le=1)
    rating_avg: float | None = Field(default=None, ge=0, le=5)
    reviews_count: int | None = Field(default=None, ge=0)
    dispute_rate: float | None = Field(default=None, ge=0, le=1)
    certifications: list[Annotated[str, Field(max_length=64)]] | None = Field(default=None, max_length=200)
    domain_age_years: float | None = Field(default=None, ge=0, le=100)
    has_physical_address: bool | None = None
    contact_consistency: float | None = Field(default=None, ge=0, le=1)
    sanctions_hit: bool | None = None
    price_vs_market_ratio: float | None = Field(default=None, gt=0, description="supplier price / market median")
    country_risk: float | None = Field(default=None, ge=0, le=1, description="0 safe .. 1 very risky")

    # --- v2 signals (all optional, additive) ---
    business_license_status: LicenseStatus | None = Field(default=None, description="registry / business-licence check")
    certification_records: list[CertificationRecord] | None = Field(default=None, max_length=200)
    storefront_age_years: float | None = Field(default=None, ge=0, le=100)
    repeat_buyer_rate: float | None = Field(default=None, ge=0, le=1)
    response_time_hours: float | None = Field(default=None, ge=0, le=24 * 365)
    dispute_rate_recent: float | None = Field(default=None, ge=0, le=1, description="last 90 days")
    refund_rate: float | None = Field(default=None, ge=0, le=1)
    deals_completed: int | None = Field(default=None, ge=0)
    deals_cancelled: int | None = Field(default=None, ge=0)
    confirmed_reports: int | None = Field(default=None, ge=0, description="buyer reports accepted after review")
    blocked: bool | None = Field(default=None, description="platform/compliance block: hard-fail red")
    review_summary: ReviewSummary | None = Field(default=None, description="verified-purchase review aggregates (rfq)")
    verification: VerificationEvidence | None = Field(default=None, description="approved verification documents (type + dates only)")
