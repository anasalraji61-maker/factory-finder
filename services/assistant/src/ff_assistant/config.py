"""Runtime configuration (pydantic-settings, env prefix ``FF_ASSISTANT_``).

Secrets (the optional LLM key, the internal token) are read from the environment only and are
kept as ``SecretStr`` so they never end up in logs or reprs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FF_ASSISTANT_", extra="ignore", env_ignore_empty=True)

    # Inter-service clients: "http" talks to the real services, "mock" uses the
    # deterministic in-process mocks (handy for running the assistant standalone).
    clients: Literal["http", "mock"] = "http"
    sourcing_url: str = "http://localhost:8101"
    logistics_url: str = "http://localhost:8102"
    trust_url: str = "http://localhost:8104"
    tracking_url: str = "http://localhost:8107"
    rfq_url: str = "http://localhost:8105"
    http_timeout_s: float = Field(default=4.0, gt=0, le=60)

    # Shared internal token (checked only when set; also forwarded to downstream services).
    internal_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FF_INTERNAL_TOKEN", "FF_ASSISTANT_INTERNAL_TOKEN"),
    )

    # Anonymous quota key. The gateway forwards X-Client-Ip (derived by its own trusted-proxy logic). It is honoured only
    # when the request carries the valid internal token, or when this flag says the deployment's network trusts the caller.
    trust_client_ip_header: bool = Field(default=False, validation_alias="FF_ASSISTANT_TRUST_CLIENT_IP_HEADER")

    default_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    max_listings: int = Field(default=3, ge=1, le=10)
    search_page_size: int = Field(default=10, ge=3, le=50)

    # Per-user daily request quota (in-memory per process unless FF_REDIS_URL is set). Identity = X-User-Id set by the gateway;
    # requests without it share a small per-client-host bucket.
    quota_per_day: int = Field(default=200, ge=1)
    anon_quota_per_day: int = Field(default=30, ge=1)
    # Share the quota counters across replicas (needs the `redis` extra). Empty = in-memory, per process.
    redis_url: str | None = Field(default=None, validation_alias=AliasChoices("FF_REDIS_URL", "FF_ASSISTANT_REDIS_URL"))

    # Optional LLM (OFF by default): FF_ASSISTANT_LLM=off|mock|anthropic.
    # Used only for low-confidence intent extraction and optional tone rewrite; never invents figures.
    llm: Literal["off", "mock", "anthropic"] = "off"
    llm_api_key: SecretStr | None = None
    llm_model: str = "claude-haiku-5-5"
    llm_base_url: str = "https://api.anthropic.com"  # any Anthropic-Messages-shaped gateway
    llm_timeout_s: float = Field(default=6.0, gt=0, le=60)
    llm_max_tokens: int = Field(default=300, ge=16, le=1000)  # hard cap on generated tokens
    llm_max_input_chars: int = Field(default=1500, ge=100, le=4000)  # hard cap on prompt text
    llm_min_confidence: float = Field(default=0.5, ge=0, le=1)
    llm_rewrite: bool = False  # optional tone rewrite of the final answer (numbers verified)


def get_settings() -> Settings:
    return Settings()
