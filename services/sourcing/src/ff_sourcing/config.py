from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .dburl import resolve_auto_create


class Settings(BaseSettings):
    """Env prefix FF_SOURCING_. Secrets come from env only; never log them."""

    model_config = SettingsConfigDict(env_prefix="FF_SOURCING_", env_file=None, extra="ignore", env_ignore_empty=True)

    # Comma separated adapter ids. Real adapters are off unless listed here.
    enabled_sources: str = "mock,native"
    # FF_SOURCING_ADAPTERS: extra adapter ids to enable (e.g. "alibaba_openapi"). Empty = mock only.
    adapters: str = ""
    adapter_timeout_s: float = 3.0
    cache_ttl_s: float = 60.0
    trust_cache_ttl_s: float = 300.0

    # Persistent supplier-owned ("native") listings. SQLite by default; see docs/DB.md.
    database_url: str = "sqlite+aiosqlite:///./sourcing.db"
    db_auto_create: bool | None = None  # None = true for SQLite, false for PostgreSQL
    internal_token: str | None = None  # FF_INTERNAL_TOKEN is also honoured (see main.py)
    max_listings_per_supplier: int = 200
    create_rate_per_hour: int = 30

    # Moderation: X-Admin-Token guards /v1/admin/*; admin endpoints answer 404 while unset.
    admin_token: SecretStr | None = Field(default=None, repr=False)
    reporter_hash_key: str = Field(default="ff-sourcing-reporter", repr=False)  # keyed hash of reporter ids
    report_rate_per_hour: int = 10  # per reporter, per process (attempts count, duplicates included)
    report_review_threshold: int = 3  # distinct open reports that move a listing to pending_review (0 = off)

    trust_mode: str = "mock"  # mock | http | off
    trust_base_url: str = "http://localhost:8104"
    trust_timeout_s: float = 0.8

    # Compliance (CLAUDE.md rule 6)
    user_agent: str = "FactoryFinderBot/0.1 (+https://github.com/factory-finder; sourcing)"
    min_request_interval_s: float = 3.0

    # Real adapter credentials (all optional, empty = adapter unconfigured)
    alibaba_app_key: str = Field(default="", repr=False)
    alibaba_app_secret: str = Field(default="", repr=False)
    alibaba_api_base: str = "https://openapi-api.alibaba.com"
    aliexpress_app_key: str = Field(default="", repr=False)
    aliexpress_app_secret: str = Field(default="", repr=False)
    aliexpress_tracking_id: str = ""
    aliexpress_api_base: str = "https://api-sg.aliexpress.com/sync"
    mic_api_key: str = Field(default="", repr=False)
    mic_api_base: str = ""  # licensed partner feed URL; no public API exists
    mic_allow_public_pages: bool = False
    s1688_app_key: str = Field(default="", repr=False)
    s1688_app_secret: str = Field(default="", repr=False)
    s1688_api_base: str = "https://gw.open.1688.com/openapi"

    @property
    def auto_create_tables(self) -> bool:
        return resolve_auto_create(self.database_url, self.db_auto_create)

    def enabled_set(self) -> set[str]:
        ids = f"{self.enabled_sources},{self.adapters}".split(",")
        return {s.strip() for s in ids if s.strip()}
