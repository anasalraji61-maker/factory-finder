"""Gateway settings (env prefix FF_GATEWAY_)."""

import logging
import secrets

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("ff_gateway")

DEFAULT_UPSTREAMS: dict[str, str] = {
    "sourcing": "http://localhost:8101",
    "logistics": "http://localhost:8102",
    "geo": "http://localhost:8103",
    "trust": "http://localhost:8104",
    "rfq": "http://localhost:8105",
    "messaging": "http://localhost:8106",
    "tracking": "http://localhost:8107",
    "notifications": "http://localhost:8108",
    "assistant": "http://localhost:8109",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FF_GATEWAY_", env_file=".env", extra="ignore", populate_by_name=True)

    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    access_ttl_seconds: int = 15 * 60
    refresh_ttl_seconds: int = 30 * 24 * 3600
    database_url: str = "sqlite+aiosqlite:///./gateway.db"
    # JSON in env, e.g. FF_GATEWAY_UPSTREAMS='{"trust":"http://trust:8104"}' (merged over defaults)
    upstreams: dict[str, str] = Field(default_factory=dict)
    internal_token: str | None = Field(default=None, validation_alias="FF_INTERNAL_TOKEN")
    upstream_timeout_seconds: float = 15.0
    max_body_bytes: int = 10 * 1024 * 1024
    rate_limit_per_minute: int = 300
    auth_rate_limit_per_minute: int = 30
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    home_client: str = "http"  # http | mock
    bcrypt_rounds: int = 12

    def resolved_secret(self) -> str:
        """Configured secret or an ephemeral per-process one (tokens die on restart)."""
        if self.jwt_secret:
            return self.jwt_secret
        generated = secrets.token_urlsafe(48)
        object.__setattr__(self, "jwt_secret", generated)
        log.warning("FF_GATEWAY_JWT_SECRET is not set: generated an ephemeral dev secret; tokens are invalid after restart")
        return generated

    def upstream_map(self) -> dict[str, str]:
        return {**DEFAULT_UPSTREAMS, **self.upstreams}
