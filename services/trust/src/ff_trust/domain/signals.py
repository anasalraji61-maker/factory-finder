"""Input signals about a supplier. Every field is optional; missing means "unknown"."""

from pydantic import BaseModel, ConfigDict, Field


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
