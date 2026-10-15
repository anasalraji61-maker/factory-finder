"""Gateway settings (env prefix FF_GATEWAY_)."""

import logging
import secrets
from typing import Literal

from pydantic import AliasChoices, Field
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
    "feed": "http://localhost:8113",
    "freight": "http://localhost:8114",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FF_GATEWAY_", env_file=".env", extra="ignore", populate_by_name=True
    )

    jwt_secret: str | None = None
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"  # symmetric only: never "none", never asymmetric-confusable
    # Key rotation: tokens signed with the previous secret still verify (never used to sign). Drop it after the longest TTL.
    jwt_secret_previous: str | None = None
    access_ttl_seconds: int = 15 * 60
    refresh_ttl_seconds: int = 30 * 24 * 3600
    database_url: str = "sqlite+aiosqlite:///./gateway.db"
    # JSON in env, e.g. FF_GATEWAY_UPSTREAMS='{"trust":"http://trust:8104"}' (merged over defaults)
    upstreams: dict[str, str] = Field(default_factory=dict)
    internal_token: str | None = Field(default=None, validation_alias="FF_INTERNAL_TOKEN")
    # Service admin token the gateway injects towards sourcing /v1/admin/moderation/* (never taken from the client).
    sourcing_admin_token: str | None = Field(default=None, validation_alias="FF_SOURCING_ADMIN_TOKEN")
    # Service admin token the gateway injects towards payments /v1/payments/outbox* (never taken from the client).
    # Service admin token the gateway injects towards media's private-file admin read (never taken from the client).
    media_admin_token: str | None = Field(default=None, validation_alias="FF_MEDIA_ADMIN_TOKEN")
    payments_admin_token: str | None = Field(default=None, validation_alias="FF_PAYMENTS_ADMIN_TOKEN")
    # Service admin tokens the gateway injects towards trust / freight / feed admin routes (never taken from the client).
    trust_admin_token: str | None = Field(default=None, validation_alias="FF_TRUST_ADMIN_TOKEN")
    freight_admin_token: str | None = Field(default=None, validation_alias="FF_FREIGHT_ADMIN_TOKEN")
    feed_admin_token: str | None = Field(default=None, validation_alias="FF_FEED_ADMIN_TOKEN")
    upstream_timeout_seconds: float = 15.0  # read/write timeout per upstream call
    upstream_connect_timeout_seconds: float = 3.0  # TCP connect (a dead host fails fast instead of after 15 s)
    upstream_pool_timeout_seconds: float = 5.0  # waiting for a free pooled connection
    upstream_max_connections: int = 200  # pool size over all upstreams
    upstream_max_keepalive_connections: int = 50
    # Per-upstream circuit breaker (proxy only): N consecutive failures (connect error, timeout, 502/503/504) open it for
    # cooldown seconds (503 upstream_unavailable + Retry-After without calling the service), then one half-open probe.
    breaker_failure_threshold: int = 5  # 0 = breaker off
    breaker_cooldown_seconds: float = 30.0
    # WebSocket tickets (POST /v1/ws-ticket): short-lived, single-use, in memory.
    ws_ticket_ttl_seconds: int = 30
    ws_ticket_max: int = 10_000
    # Keep accepting the access token in the ?token= query / Authorization header at the websocket
    # handshake (compat for old app builds). Set false once clients use ?ticket=.
    ws_allow_token_param: bool = False  # mobile fetches tickets (chat_socket_provider); flip to true only for pre-ticket app builds
    ws_max_connections_per_user: int = 5  # concurrent proxied sockets per user, then close 4429 (0 = off)
    ws_max_session_seconds: int = 4 * 3600  # proxied socket lifetime, then close 1001 and re-handshake (0 = off)
    ws_ticket_rate_limit_per_minute: int = 30  # POST /v1/ws-ticket per user (0 = off), on top of the HTTP limits
    max_body_bytes: int = 10 * 1024 * 1024  # media uploads (multipart); every other route class is capped by json_max_body_bytes
    json_max_body_bytes: int = 1024 * 1024
    body_read_timeout_seconds: float = 30.0  # whole request body must arrive within this (media: media_body_read_timeout_seconds)
    media_body_read_timeout_seconds: float = 120.0
    # Per account (hashed email/phone) failed password attempts per minute before logins for it answer 429, on top of the per-IP limit.
    login_fail_limit_per_minute: int = 10
    # POST /v1/auth/register attempts per client IP per hour (0 = off); limits account-enumeration via 409 account_exists.
    register_per_hour: int = 10
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
    # FF_REDIS_URL is accepted as well. The same Redis also backs the ws tickets and per-user socket counters.
    redis_url: str | None = Field(default=None, validation_alias=AliasChoices("FF_GATEWAY_REDIS_URL", "FF_REDIS_URL", "redis_url"))
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
    # Password reset (POST /v1/auth/password/forgot|reset); needs a mail backend, otherwise forgot is a silent no-op.
    password_reset_ttl_seconds: int = 30 * 60
    password_forgot_per_minute: int = 1  # per email+IP, silently throttled (same 202)
    password_forgot_per_email_per_minute: int = 3  # per email over all IPs (limits mailbox flooding)
    password_reset_url_template: str | None = None  # e.g. https://app.example.com/reset?token={token}
    # Optional link template put in the mail, e.g. https://app.example.com/verify?token={token}
    verify_url_template: str | None = None

    # Account deletion / data export (store requirements; docs/decisions/account-deletion.md)
    # Days between DELETE /v1/me and the irreversible anonymization (0 = immediately). Login during the grace period cancels it.
    deletion_grace_days: int = Field(default=0, ge=0, le=90)
    privacy_rate_limit_per_minute: int = 3  # per user, for DELETE /v1/me and GET /v1/me/export together (0 = off)
    privacy_timeout_seconds: float = 10.0  # per upstream call during export / erasure fan-out
    export_max_bytes: int = 5 * 1024 * 1024  # cap of the whole export bundle (and of each service's share)
    deletion_max_attempts: int = 12  # then the job is marked dead (visible in /v1/admin/account-deletions)
    deletion_worker_interval_seconds: float = 60.0  # background retry/grace sweep; 0 disables the loop

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
