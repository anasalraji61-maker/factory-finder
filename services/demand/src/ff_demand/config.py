"""Service configuration. Prefix ``FF_DEMAND_``; the kill-switch is ``FF_DEMAND_ENABLED``."""

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ff_demand.dburl import resolve_auto_create


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FF_DEMAND_", extra="ignore", populate_by_name=True, env_ignore_empty=True
    )

    database_url: str = "sqlite+aiosqlite:///./demand.db"
    # Create tables at startup (dev). None = auto: true for SQLite, false for PostgreSQL
    # (production schemas come from Alembic migrations: ``alembic upgrade head``).
    db_auto_create: bool | None = None

    @property
    def auto_create_tables(self) -> bool:
        return resolve_auto_create(self.database_url, self.db_auto_create)

    internal_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FF_INTERNAL_TOKEN", "FF_DEMAND_INTERNAL_TOKEN"),
    )

    # global kill-switch: OFF by default. Off => approve / mark-published return 403.
    enabled: bool = False
    daily_cap: int = Field(default=20, ge=0)  # approvals per UTC day

    sourcing_base_url: str = "http://localhost:8101"
    sourcing_timeout_seconds: float = Field(default=5.0, gt=0)
    use_mock_sourcing: bool = False
    max_candidates: int = Field(default=3, ge=1, le=10)

    # retention (days, 0 = keep forever): purges ignored/no_match signals and rejected drafts
    # (+ their signal).
    # Draft/approved/published drafts are audit records and are never purged.
    signal_retention_days: int = Field(default=90, ge=0)
    rejected_draft_retention_days: int = Field(default=90, ge=0)

    # Compliance (CLAUDE.md rules 6-7)
    thread_cooldown_hours: int = Field(default=72, ge=1)  # one approved reply per thread/author
    blocked_domains: str = ""  # comma-separated, added to compliance.DEFAULT_BLOCKED_DOMAINS
    blocked_sources: str = ""  # comma-separated source names whose robots/ToS forbid automation
    publisher_enabled: bool = False  # real publisher adapter: OFF unless explicitly enabled
    min_host_interval_seconds: float = Field(default=3.0, ge=3.0)  # >= 1 req / 3 s per host
    user_agent: str = "FactoryFinderBot/0.1 (+https://factoryfinder.example/bot; sourcing platform)"

    @field_validator("user_agent")
    @classmethod
    def _honest_ua(cls, v: str) -> str:
        from ff_demand.polite import validate_user_agent

        return validate_user_agent(v)

    @property
    def blocked_domain_set(self) -> set[str]:
        from ff_demand.compliance import DEFAULT_BLOCKED_DOMAINS

        extra = {d.strip().casefold() for d in self.blocked_domains.split(",") if d.strip()}
        return set(DEFAULT_BLOCKED_DOMAINS) | extra

    @property
    def blocked_source_set(self) -> set[str]:
        return {d.strip().casefold() for d in self.blocked_sources.split(",") if d.strip()}

    signal_source: str = "mock"  # only "mock" ships; real sources must be official APIs

    @property
    def internal_token_value(self) -> str | None:
        return self.internal_token.get_secret_value() or None if self.internal_token else None
