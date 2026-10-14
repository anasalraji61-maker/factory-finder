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
    provider: str = "mock"  # mock | licensed
    provider_api_key: str | None = None
    refresh_min_interval_seconds: int = 60
    internal_token: str | None = None  # FF_INTERNAL_TOKEN is also honoured (see main.py)
