from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ff_media.dburl import resolve_auto_create


class Settings(BaseSettings):
    """Env prefix FF_MEDIA_. Secrets come from the environment only; none has a default."""

    model_config = SettingsConfigDict(env_prefix="FF_MEDIA_", env_file=".env", extra="ignore", env_ignore_empty=True)

    database_url: str = "sqlite+aiosqlite:///./media.db"
    db_auto_create: bool | None = None  # None = auto: true for SQLite, false for PostgreSQL (use Alembic)

    @property
    def auto_create_tables(self) -> bool:
        return resolve_auto_create(self.database_url, self.db_auto_create)

    internal_token: str | None = None  # FF_INTERNAL_TOKEN is also honoured

    # Absolute URLs handed to clients: "<public_base_url>/v1/media/files/<id>.<ext>". Point it at the public
    # gateway origin (e.g. https://api.example.com). Unset -> relative "/v1/media/files/..." paths.
    public_base_url: str | None = None

    storage_backend: str = "local"  # local | s3 (s3 is UNVERIFIED)
    storage_root: str = "./media-data"

    # S3-compatible storage (UNVERIFIED against a real bucket). Credentials: environment only.
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_prefix: str = "media/"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None

    # Private files (visibility=private / kind=verification): short-lived HMAC-signed URLs. REQUIRED when
    # FF_ENV=production; otherwise a random per-process key is used (links die on restart, fine for dev).
    signing_key: SecretStr | None = None
    signed_url_ttl_seconds: int = 300
    # Service admin token (X-Admin-Token) for GET /v1/media/admin/files/{id}; the gateway injects it. 404 when unset.
    admin_token: SecretStr | None = None

    max_upload_bytes: int = 5 * 1024 * 1024
    max_dimension: int = 8000  # per side, pixels (decompression-bomb guard)
    max_pixels: int = 40_000_000
    jpeg_quality: int = 85
    max_files_per_user: int = 200
    max_uploads_per_hour: int = 30
    max_bytes_per_user: int = 100 * 1024 * 1024  # sum of stored ORIGINAL sizes per user (variants add at most ~1x on top)
    max_concurrent_processing: int = 4  # simultaneous decode/re-encode jobs per process (memory guard)
    sweep_min_age_seconds: int = 3600  # orphan blobs younger than this are never swept (in-flight uploads)
    sweep_batch: int = 500  # FF_MEDIA_SWEEP_BATCH: rows/blobs handled per sweep batch
    sweep_max_seconds: float = 30.0  # FF_MEDIA_SWEEP_MAX_SECONDS: runtime budget per sweep_orphans call

    @property
    def base(self) -> str:
        return (self.public_base_url or "").rstrip("/")
