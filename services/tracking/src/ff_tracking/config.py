from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from ff_tracking.dburl import resolve_auto_create


class Settings(BaseSettings):
    """Env prefix FF_TRACKING_. Secrets come from env only; never log them."""

    model_config = SettingsConfigDict(env_prefix="FF_TRACKING_", env_file=".env", extra="ignore", env_ignore_empty=True)

    database_url: str = "sqlite+aiosqlite:///./tracking.db"
    # Create tables at startup (dev). None = auto: true for SQLite, false for PostgreSQL
    # (production schemas come from Alembic migrations: ``alembic upgrade head``).
    db_auto_create: bool | None = None

    @property
    def auto_create_tables(self) -> bool:
        return resolve_auto_create(self.database_url, self.db_auto_create)
    provider: str = "mock"  # mock (default, no network) | http (licensed APIs below) | <other> = stub
    provider_api_key: str | None = None
    refresh_min_interval_seconds: int = 60
    max_shipments_per_user: int = 200  # FF_TRACKING_MAX_SHIPMENTS_PER_USER; each create calls the provider
    internal_token: str | None = None  # FF_INTERNAL_TOKEN is also honoured (see main.py)
    # --- real providers (all OFF unless provider=http AND a base URL + key are set; env only) ---
    container_base_url: str = ""
    container_api_key: str | None = None
    awb_base_url: str = ""
    awb_api_key: str | None = None
    vessel_base_url: str = ""
    vessel_api_key: str | None = None
    http_min_interval_seconds: float = 3.0  # per host, clamped to >= 3
    http_cache_ttl_seconds: float = 3600.0
    fallback_to_mock: bool = True  # on provider failure answer with mock data + `warning`
    # --- background refresh of active shipments (off by default) ---
    refresh_job_enabled: bool = False
    refresh_job_interval_hours: float = 6.0  # a shipment is refreshed at most this often
    refresh_job_poll_seconds: float = 600.0
    refresh_job_batch_size: int = 50
    # --- relay of tracking_outbox to notifications (off by default) ---
    notify_relay: str = "off"  # off | on  (FF_TRACKING_NOTIFY_RELAY)
    notify_base_url: str = ""  # notifications base URL, e.g. http://localhost:8108
    notify_batch_size: int = 100  # <= 100 (contract max)
    notify_max_attempts: int = 8  # then the row is marked dead
    notify_backoff_base_seconds: float = 30.0  # doubles per attempt
    notify_backoff_max_seconds: float = 3600.0
    notify_poll_seconds: float = 30.0
    notify_timeout_seconds: float = 10.0
    outbox_retention_days: int = 30  # delivered/dead outbox rows older than this are purged by the relay
