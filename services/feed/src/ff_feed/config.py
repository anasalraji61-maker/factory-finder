"""Service configuration. Prefix ``FF_FEED_``; secrets come from the environment only."""

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ff_feed.dburl import resolve_auto_create


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FF_FEED_", extra="ignore", populate_by_name=True, env_ignore_empty=True
    )

    database_url: str = "sqlite+aiosqlite:///./feed.db"
    # None = auto: create tables at startup for SQLite, never for PostgreSQL (use Alembic).
    db_auto_create: bool | None = None

    @property
    def auto_create_tables(self) -> bool:
        return resolve_auto_create(self.database_url, self.db_auto_create)

    internal_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("FF_INTERNAL_TOKEN", "FF_FEED_INTERNAL_TOKEN"),
    )
    # Moderation endpoints (/v1/admin/feed/*). Unset => they answer 404 (feature disabled).
    admin_token: SecretStr | None = None

    # Media URLs must live under the media service path prefix. Absolute URLs are accepted only
    # when they start with this origin (the same value as FF_MEDIA_PUBLIC_BASE_URL); relative
    # "/v1/media/files/<id>.<ext>" paths are always accepted.
    media_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FF_FEED_MEDIA_BASE_URL", "FF_MEDIA_PUBLIC_BASE_URL"),
    )

    # moderation
    report_hide_threshold: int = Field(default=3, ge=1, le=100)  # distinct reporters
    # A report counts toward auto-hide only if the reporter was first seen at least this long ago
    # (reports are always stored). 0 disables the delay.
    report_min_account_age_seconds: int = Field(default=86400, ge=0)

    # caps
    max_posts_per_supplier: int = Field(default=500, ge=1)
    max_follows_per_user: int = Field(default=500, ge=1)
    max_comments_per_post: int = Field(default=1000, ge=1)
    max_page_size: int = Field(default=50, ge=1, le=100)
    default_page_size: int = Field(default=20, ge=1, le=100)
    trending_window_days: int = Field(default=14, ge=1, le=90)

    # per-user rate limits: N actions per rolling window (0 disables the limit)
    rate_window_seconds: int = Field(default=3600, ge=1)
    rate_posts: int = Field(default=10, ge=0)
    rate_comments: int = Field(default=30, ge=0)
    rate_likes: int = Field(default=200, ge=0)
    rate_follows: int = Field(default=60, ge=0)
    rate_reports: int = Field(default=20, ge=0)

    @property
    def internal_token_value(self) -> str | None:
        return self.internal_token.get_secret_value() or None if self.internal_token else None

    @property
    def admin_token_value(self) -> str | None:
        return self.admin_token.get_secret_value() or None if self.admin_token else None
