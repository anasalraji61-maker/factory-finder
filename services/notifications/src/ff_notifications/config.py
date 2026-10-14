"""Service configuration (environment prefix ``FF_NOTIFICATIONS_``)."""

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ff_notifications.dburl import resolve_auto_create


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FF_NOTIFICATIONS_", extra="ignore", populate_by_name=True, env_ignore_empty=True
    )

    database_url: str = "sqlite+aiosqlite:///./notifications.db"
    # Create tables at startup (dev). None = auto: true for SQLite, false for PostgreSQL
    # (production schemas come from Alembic migrations: ``alembic upgrade head``).
    db_auto_create: bool | None = None

    @property
    def auto_create_tables(self) -> bool:
        return resolve_auto_create(self.database_url, self.db_auto_create)
    internal_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FF_INTERNAL_TOKEN", "FF_NOTIFICATIONS_INTERNAL_TOKEN"),
    )

    # sourcing client
    sourcing_base_url: str = "http://localhost:8101"
    sourcing_timeout_seconds: float = Field(default=5.0, gt=0)
    use_mock_sourcing: bool = False

    # alerts
    cooldown_hours: float = Field(default=24.0, ge=0)
    default_drop_threshold_pct: str = "5"
    equivalent_min_saving_pct: str = "0"
    max_watches_per_user: int = Field(default=100, ge=1)
    page_size_default: int = Field(default=20, ge=1)
    page_size_max: int = Field(default=100, ge=1)

    # push: "mock" or "fcm". FCM is a stub and disabled unless explicitly enabled.
    push_provider: str = "mock"
    fcm_enabled: bool = False
    fcm_server_key: SecretStr | None = None

    # scheduler (periodic evaluation of all watches); off by default and in tests
    scheduler_enabled: bool = False
    scheduler_interval_seconds: float = Field(default=900.0, ge=1)

    @property
    def internal_token_value(self) -> str | None:
        return self.internal_token.get_secret_value() or None if self.internal_token else None
