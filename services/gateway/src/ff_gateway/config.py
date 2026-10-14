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
    "demand": "http://localhost:8110",
    "payments": "http://localhost:8111",
    "media": "http://localhost:8112",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FF_GATEWAY_", env_file=".env", extra="ignore", populate_by_name=True
    )

    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    access_ttl_seconds: int = 15 * 60
    refresh_ttl_seconds: int = 30 * 24 * 3600
    database_url: str = "sqlite+aiosqlite:///./gateway.db"
    # JSON in env, e.g. FF_GATEWAY_UPSTREAMS='{"trust":"http://trust:8104"}' (merged over defaults)
    upstreams: dict[str, str] = Field(default_factory=dict)
    internal_token: str | None = Field(default=None, validation_alias="FF_INTERNAL_TOKEN")
    # Service admin token the gateway injects towards sourcing /v1/admin/moderation/* (never taken from the client).
    sourcing_admin_token: str | None = Field(default=None, validation_alias="FF_SOURCING_ADMIN_TOKEN")
    upstream_timeout_seconds: float = 15.0
    max_body_bytes: int = 10 * 1024 * 1024
    rate_limit_per_minute: int = 300
    # Public image GETs (feeds load many thumbnails) get their own, larger bucket per IP.
    media_rate_limit_per_minute: int = 3000
    # Per authenticated user on write routes (POST/PUT/PATCH/DELETE outside /v1/auth); 0 disables.
    user_write_rate_limit_per_minute: int = 120
    rate_limit_max_keys: int = 50_000  # cap on limiter memory (oldest windows are evicted)
    # FF_GATEWAY_TRUSTED_PROXIES: comma-separated CIDRs/IPs of reverse proxies whose
    # X-Forwarded-For is honoured (only when the direct peer is in this list). Empty = never.
    trusted_proxies: str = ""
    auth_rate_limit_per_minute: int = 30
    cors_origins: list[str] = Field(
        default_factory=list
    )  # empty = no cross-origin access (native app needs none)
    admin_token: str | None = None  # FF_GATEWAY_ADMIN_TOKEN; unset -> /v1/admin/* answers 404
    serve_admin: bool = (
        False  # FF_GATEWAY_SERVE_ADMIN: serve apps/admin at /admin (same-origin, no CORS needed)
    )
    admin_dir: str | None = None  # FF_GATEWAY_ADMIN_DIR override (default: <repo>/apps/admin)
    home_client: str = "http"  # http | mock
    bcrypt_rounds: int = 12
    # Rate-limit store: unset -> in-memory (per process). FF_GATEWAY_REDIS_URL=redis://host:6379/0 shares counters
    # across replicas (needs the "redis" extra; falls back to memory with a warning if unavailable).
    redis_url: str | None = None
    # Email verification. FF_GATEWAY_REQUIRE_EMAIL_VERIFIED=true blocks payments writes, supplier claims
    # and supplier listing writes (/v1/my) for accounts whose email is not verified. Default off.
    require_email_verified: bool = False
    email_verification_ttl_seconds: int = 24 * 3600
    resend_verification_per_minute: int = 1  # per email address, silently throttled (the per-IP auth limit gives 429)
    # Mail adapter: off (default, nothing is sent and no tokens are issued) | mock (in-memory outbox) | smtp
    mail_backend: str = "off"
    mail_from: str = "no-reply@localhost"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    # Optional link template put in the mail, e.g. https://app.example.com/verify?token={token}
    verify_url_template: str | None = None

    def trusted_proxy_networks(self) -> list:
        from ff_gateway.domain.client_ip import parse_networks

        return parse_networks(self.trusted_proxies)

    def resolved_secret(self) -> str:
        """Configured secret or an ephemeral per-process one (tokens die on restart)."""
        if self.jwt_secret:
            return self.jwt_secret
        generated = secrets.token_urlsafe(48)
        object.__setattr__(self, "jwt_secret", generated)
        log.warning(
            "FF_GATEWAY_JWT_SECRET is not set: generated an ephemeral dev secret; tokens are invalid after restart"
        )
        return generated

    def upstream_map(self) -> dict[str, str]:
        return {**DEFAULT_UPSTREAMS, **self.upstreams}
