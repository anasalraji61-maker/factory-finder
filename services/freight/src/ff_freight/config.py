"""Service configuration. Prefix ``FF_FREIGHT_``; secrets come from the environment only."""

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ff_freight.dburl import resolve_auto_create


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FF_FREIGHT_", extra="ignore", populate_by_name=True, env_ignore_empty=True
    )

    database_url: str = "sqlite+aiosqlite:///./freight.db"
    # None = auto: create tables at startup for SQLite, never for PostgreSQL (use Alembic).
    db_auto_create: bool | None = None

    @property
    def auto_create_tables(self) -> bool:
        return resolve_auto_create(self.database_url, self.db_auto_create)

    internal_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FF_INTERNAL_TOKEN", "FF_FREIGHT_INTERNAL_TOKEN"),
    )
    # Admin endpoints (/v1/admin/freight/*): forwarder approval + moderation. Unset => 404.
    admin_token: SecretStr | None = None

    # moderation
    report_hide_threshold: int = Field(default=3, ge=1, le=100)  # distinct reporters

    # caps
    max_open_requests_per_buyer: int = Field(default=50, ge=1)
    max_quotes_per_request: int = Field(default=50, ge=1)
    max_lanes_per_forwarder: int = Field(default=50, ge=1)
    max_applications_per_user: int = Field(default=5, ge=1)
    max_page_size: int = Field(default=50, ge=1, le=100)
    default_page_size: int = Field(default=20, ge=1, le=100)

    # ranking: weights of the explainable score (normalised to sum 1) and the rating prior
    weight_price: int = Field(default=50, ge=0, le=100)
    weight_transit: int = Field(default=30, ge=0, le=100)
    weight_rating: int = Field(default=20, ge=0, le=100)

    # per-user rate limits: N actions per rolling window (0 disables the limit)
    rate_window_seconds: int = Field(default=3600, ge=1)
    rate_applications: int = Field(default=3, ge=0)
    rate_requests: int = Field(default=10, ge=0)
    rate_quotes: int = Field(default=60, ge=0)
    rate_ratings: int = Field(default=20, ge=0)
    rate_reports: int = Field(default=20, ge=0)

    @property
    def internal_token_value(self) -> str | None:
        return self.internal_token.get_secret_value() or None if self.internal_token else None

    @property
    def admin_token_value(self) -> str | None:
        return self.admin_token.get_secret_value() or None if self.admin_token else None
