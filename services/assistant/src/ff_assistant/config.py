"""Runtime configuration (pydantic-settings, env prefix ``FF_ASSISTANT_``).

Secrets (the optional LLM key, the internal token) are read from the environment only and are
kept as ``SecretStr`` so they never end up in logs or reprs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FF_ASSISTANT_", extra="ignore")

    # Inter-service clients: "http" talks to the real services, "mock" uses the
    # deterministic in-process mocks (handy for running the assistant standalone).
    clients: Literal["http", "mock"] = "http"
    sourcing_url: str = "http://localhost:8101"
    logistics_url: str = "http://localhost:8102"
    trust_url: str = "http://localhost:8104"
    tracking_url: str = "http://localhost:8107"
    http_timeout_s: float = Field(default=4.0, gt=0, le=60)

    # Shared internal token (checked only when set; also forwarded to downstream services).
    internal_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FF_INTERNAL_TOKEN", "FF_ASSISTANT_INTERNAL_TOKEN"),
    )

    default_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    max_listings: int = Field(default=3, ge=1, le=10)
    search_page_size: int = Field(default=10, ge=3, le=50)

    # Optional LLM refinement of low-confidence parses. Never required.
    llm_provider: Literal["none", "mock", "anthropic"] = "mock"
    llm_api_key: SecretStr | None = None
    llm_model: str = "claude-haiku-5-5"
    llm_base_url: str = "https://api.anthropic.com"
    llm_timeout_s: float = Field(default=6.0, gt=0, le=60)
    llm_min_confidence: float = Field(default=0.5, ge=0, le=1)


def get_settings() -> Settings:
    return Settings()
