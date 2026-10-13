from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env prefix FF_TRACKING_. Secrets come from env only; never log them."""

    model_config = SettingsConfigDict(env_prefix="FF_TRACKING_", env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./tracking.db"
    provider: str = "mock"  # mock | licensed
    provider_api_key: str | None = None
    refresh_min_interval_seconds: int = 60
    internal_token: str | None = None  # FF_INTERNAL_TOKEN is also honoured (see main.py)
