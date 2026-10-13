from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env prefix FF_SOURCING_. Secrets come from env only; never log them."""

    model_config = SettingsConfigDict(env_prefix="FF_SOURCING_", env_file=None, extra="ignore")

    # Comma separated adapter ids. Real adapters are off unless listed here.
    enabled_sources: str = "mock"
    adapter_timeout_s: float = 3.0
    cache_ttl_s: float = 60.0
    trust_cache_ttl_s: float = 300.0

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

    def enabled_set(self) -> set[str]:
        return {s.strip() for s in self.enabled_sources.split(",") if s.strip()}
