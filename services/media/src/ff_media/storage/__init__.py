from ff_media.config import Settings
from ff_media.storage.base import StorageBackend, make_key, valid_key
from ff_media.storage.local import LocalDiskStorage
from ff_media.storage.s3 import S3Storage


def build_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "s3":
        return S3Storage(
            settings.s3_bucket or "", prefix=settings.s3_prefix, region=settings.s3_region,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id.get_secret_value() if settings.s3_access_key_id else None,
            secret_access_key=settings.s3_secret_access_key.get_secret_value() if settings.s3_secret_access_key else None,
        )  # fmt: skip
    if settings.storage_backend != "local":
        raise ValueError(f"unknown FF_MEDIA_STORAGE_BACKEND {settings.storage_backend!r}")
    return LocalDiskStorage(settings.storage_root)


__all__ = ["LocalDiskStorage", "S3Storage", "StorageBackend", "build_storage", "make_key", "valid_key"]
