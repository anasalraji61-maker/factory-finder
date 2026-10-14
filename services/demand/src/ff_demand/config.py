"""Service configuration. Prefix ``FF_DEMAND_``; the kill-switch is ``FF_DEMAND_ENABLED``."""

from pydantic import AliasChoices, Field, SecretStr
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

    signal_source: str = "mock"  # only "mock" ships; real sources must be official APIs

    @property
    def internal_token_value(self) -> str | None:
        return self.internal_token.get_secret_value() or None if self.internal_token else None
