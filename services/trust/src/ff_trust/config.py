"""Service settings (env prefix FF_TRUST_) and the scoring configuration."""

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_WEIGHTS: dict[str, float] = {
    "years_in_business": 8,
    "verified": 8,
    "third_party_audit": 8,
    "transactions_count": 8,
    "response_rate": 5,
    "rating_avg": 8,
    "reviews_count": 4,
    "dispute_rate": 15,
    "certifications": 6,
    "domain_age_years": 4,
    "has_physical_address": 4,
    "contact_consistency": 5,
    "price_vs_market_ratio": 15,
    "country_risk": 6,
}


class ScoringConfig(BaseModel):
    """Everything that tunes the score. Weights are the max |points| of each signal."""

    weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    baseline: int = 40
    green_min: int = 75
    yellow_min: int = 50
    min_signals: int = 4  # fewer known signals than this -> band "unknown"
    sanctions_cap: int = 20
    dispute_severe_rate: float = 0.15
    dispute_severe_cap: int = 49
    dispute_high_rate: float = 0.08
    dispute_high_cap: int = 69
    too_cheap_ratio: float = 0.4
    too_cheap_cap: int = 59
    model_version: str = "trust-v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FF_TRUST_", env_file=".env", extra="ignore", populate_by_name=True)

    adapter: str = "mock"  # mock | alibaba | made_in_china (real ones are disabled stubs)
    cache_ttl_seconds: int = 300
    cache_max_entries: int = 5000
    max_batch: int = 50
    internal_token: str | None = Field(default=None, validation_alias="FF_INTERNAL_TOKEN")
