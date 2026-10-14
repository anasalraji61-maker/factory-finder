"""Input signals about a supplier. Every field is optional; missing means "unknown"."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LicenseStatus = Literal["verified", "pending", "unverified", "expired", "mismatch"]


class CertificationRecord(BaseModel):
    """A certificate with optional expiry (expired ones stop counting)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    expires_on: date | None = None


class SupplierSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: str | None = None
    years_in_business: float | None = Field(default=None, ge=0, le=200)
    verified: bool | None = None
    third_party_audit: bool | None = None
    transactions_count: int | None = Field(default=None, ge=0)
    response_rate: float | None = Field(default=None, ge=0, le=1)
    rating_avg: float | None = Field(default=None, ge=0, le=5)
    reviews_count: int | None = Field(default=None, ge=0)
    dispute_rate: float | None = Field(default=None, ge=0, le=1)
    certifications: list[str] | None = None
    domain_age_years: float | None = Field(default=None, ge=0, le=100)
    has_physical_address: bool | None = None
    contact_consistency: float | None = Field(default=None, ge=0, le=1)
    sanctions_hit: bool | None = None
    price_vs_market_ratio: float | None = Field(default=None, gt=0, description="supplier price / market median")
    country_risk: float | None = Field(default=None, ge=0, le=1, description="0 safe .. 1 very risky")

    # --- v2 signals (all optional, additive) ---
    business_license_status: LicenseStatus | None = Field(default=None, description="registry / business-licence check")
    certification_records: list[CertificationRecord] | None = None
    storefront_age_years: float | None = Field(default=None, ge=0, le=100)
    repeat_buyer_rate: float | None = Field(default=None, ge=0, le=1)
    response_time_hours: float | None = Field(default=None, ge=0, le=24 * 365)
    dispute_rate_recent: float | None = Field(default=None, ge=0, le=1, description="last 90 days")
    refund_rate: float | None = Field(default=None, ge=0, le=1)
    deals_completed: int | None = Field(default=None, ge=0)
    deals_cancelled: int | None = Field(default=None, ge=0)
    confirmed_reports: int | None = Field(default=None, ge=0, description="buyer reports accepted after review")
    blocked: bool | None = Field(default=None, description="platform/compliance block: hard-fail red")
