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

    # delivery providers (all OFF by default): FF_NOTIFY_PUSH=off|mock|fcm,
    # FF_NOTIFY_EMAIL=off|mock|smtp
    notify_push: str = Field(
        default="off", validation_alias=AliasChoices("FF_NOTIFY_PUSH", "FF_NOTIFICATIONS_PUSH")
    )
    notify_email: str = Field(
        default="off", validation_alias=AliasChoices("FF_NOTIFY_EMAIL", "FF_NOTIFICATIONS_EMAIL")
    )
    # FCM credentials: ONLY from env (service-account JSON content or a path to the file)
    fcm_project_id: str | None = Field(default=None, validation_alias="FF_NOTIFY_FCM_PROJECT_ID")
    fcm_credentials_json: SecretStr | None = Field(
        default=None, validation_alias="FF_NOTIFY_FCM_CREDENTIALS_JSON"
    )
    fcm_credentials_file: str | None = Field(
        default=None, validation_alias="FF_NOTIFY_FCM_CREDENTIALS_FILE"
    )
    smtp_host: str | None = Field(default=None, validation_alias="FF_NOTIFY_SMTP_HOST")
    smtp_port: int = Field(default=587, validation_alias="FF_NOTIFY_SMTP_PORT")
    smtp_user: str | None = Field(default=None, validation_alias="FF_NOTIFY_SMTP_USER")
    smtp_password: SecretStr | None = Field(
        default=None, validation_alias="FF_NOTIFY_SMTP_PASSWORD"
    )
    smtp_from: str | None = Field(default=None, validation_alias="FF_NOTIFY_SMTP_FROM")

    # delivery pipeline
    max_devices_per_user: int = Field(default=10, ge=1)
    delivery_max_attempts: int = Field(default=5, ge=1)
    delivery_backoff_base_seconds: float = Field(default=30.0, ge=0)
    delivery_backoff_max_seconds: float = Field(default=3600.0, ge=0)

    # scheduler (periodic evaluation of all watches); off by default and in tests
    scheduler_enabled: bool = False
    scheduler_interval_seconds: float = Field(default=900.0, ge=1)

    @property
    def internal_token_value(self) -> str | None:
        return self.internal_token.get_secret_value() or None if self.internal_token else None
