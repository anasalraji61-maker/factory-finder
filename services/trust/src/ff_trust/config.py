"""Service settings (env prefix FF_TRUST_) and the scoring configuration."""

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ff_trust.dburl import resolve_auto_create

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
    # v2 signals
    "business_license_status": 5,
    "storefront_age_years": 2,
    "repeat_buyer_rate": 3,
    "response_time_hours": 2,
    "refund_rate": 3,
    "deal_outcomes": 4,
    "confirmed_reports": 8,
    "platform_reviews": 6,  # bounded: verified-purchase reviews from rfq
    "document_verification": 6,  # bounded, never negative: approved legal / identity documents
    "facility_evidence": 4,  # bounded, never negative: approved factory photos / certificates
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
    hard_fail_cap: int = 20  # blocked flag (platform/compliance block), same effect as a sanctions hit
    price_anomaly_low: float = 0.6  # price/market below this (or above price_anomaly_high) is flagged
    price_anomaly_high: float = 2.5
    cert_expiring_days: int = 60
    review_prior_mean: float = 3.8  # Bayesian shrinkage prior for the average rating
    review_prior_weight: float = 10.0  # pseudo-reviews at the prior mean
    platform_review_prior_weight: float = 8.0  # pseudo-reviews at the prior mean for the rfq review summary
    platform_review_full_n: int = 10  # below this many reviews the signal is linearly dampened
    platform_review_sub_share: float = 0.3  # share of the sub-ratings mean inside the signal
    deal_prior_rate: float = 0.85
    deal_prior_weight: float = 8.0
    dispute_recent_weight: float = 0.6  # weight of the last-90-day dispute rate vs the lifetime rate
    doc_decay_days: int = 90  # approved documents lose weight over the last N days before expiry
    doc_decay_floor: float = 0.5  # weight left on the expiry day (0 afterwards)
    doc_default_validity_days: int = 730  # documents without an expiry stay valid this long after approval
    model_version: str = "trust-v2"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FF_TRUST_", env_file=".env", extra="ignore", populate_by_name=True, env_ignore_empty=True)

    database_url: str = "sqlite+aiosqlite:///./data/trust.db"  # FF_TRUST_DATABASE_URL; postgresql://... is rewritten to asyncpg
    db_auto_create: bool | None = None  # FF_TRUST_DB_AUTO_CREATE; unset = true for SQLite, false for PostgreSQL (use Alembic)
    adapter: str = "mock"  # mock | alibaba | made_in_china (real ones are disabled stubs)
    cache_ttl_seconds: int = 300
    cache_max_entries: int = 5000
    max_batch: int = 50
    report_rate_limit: int = 5  # buyer reports per user per window
    report_rate_window_seconds: int = 3600
    history_months: int = 12
    reviews_source: str = "off"  # off | mock | http (rfq review-summary)
    reviews_base_url: str = "http://rfq:8105"
    reviews_timeout_seconds: float = 2.0
    reviews_cache_ttl_seconds: float = 60.0
    admin_token: str | None = None  # FF_TRUST_ADMIN_TOKEN; unset -> verification admin endpoints answer 404
    verification_rate_limit: int = 10  # document submissions per supplier per window
    verification_rate_window_seconds: int = 3600
    verification_max_docs_per_supplier: int = 30  # pending + approved
    verification_max_docs_per_type: int = 5
    verification_max_files: int = 10
    verification_max_total_docs: int = 20000
    verification_hash_key: str | None = None  # HMAC key for document-number fingerprints; REQUIRED when FF_ENV=production
    report_max_total: int = 20000  # stored buyer reports (accepted ones are never evicted)
    report_min_account_age_seconds: int = 259200  # reporter accounts younger than this (or with an unverified email) use the low-trust bucket; needs gateway headers
    report_max_low_trust: int = 2000  # size of that bucket (evicted first, never evicts established reports)
    report_retention_days: int = 365  # rejected / stale pending reports are purged after this; accepted are kept
    snapshot_max_per_supplier: int = 500
    snapshot_max_total: int = 200000
    snapshot_retention_days: int = 730
    # Verification documents must be PRIVATE media refs (/v1/media/private/<id>.<ext>); public /v1/media/files/ refs are
    # rejected. Format check only: trust never calls media (the owner/admin read through signed URLs, see docs/decisions/media-private.md).
    verification_media_prefixes: list[str] = ["/v1/media/private/"]
    verification_media_hosts: list[str] = []  # absolute media URLs need a host listed here; empty = relative paths only
    verification_allow_http: bool = False
    internal_token: str | None = Field(default=None, validation_alias="FF_INTERNAL_TOKEN")

    @property
    def auto_create_tables(self) -> bool:
        return resolve_auto_create(self.database_url, self.db_auto_create)
