from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FF_LOGISTICS_", extra="ignore", populate_by_name=True)

    geo_provider: str = "http"  # http | mock
    geo_url: str = "http://localhost:8103"
    fx_provider: str = "mock"  # mock | ecb (free, no key; falls back to mock on errors)
    fx_url: str = "https://api.frankfurter.dev/v1/latest"
    fx_cache_ttl_seconds: int = 6 * 3600
    internal_token: str | None = Field(default=None, validation_alias="FF_INTERNAL_TOKEN")
    # Live freight rates (OFF by default; UNVERIFIED Freightos-style API). Key from env only.
    freight_provider: str = "mock"  # mock | http (falls back to built-in tables on any error)
    freight_url: str = ""
    freight_api_key: str = Field(default="", repr=False)
    freight_min_interval_s: float = 3.0
    freight_cache_ttl_seconds: int = 6 * 3600
    freight_max_calls_per_quote: int = 6
