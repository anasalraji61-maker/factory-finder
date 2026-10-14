from __future__ import annotations


class MediaError(Exception):
    status_code = 400
    code = "error"

    def __init__(self, message: str, details: dict | None = None, headers: dict | None = None) -> None:
        super().__init__(message)
        self.message, self.details, self.headers = message, details or {}, headers or {}


class MissingUser(MediaError):
    status_code, code = 401, "missing_user"


class NotFound(MediaError):
    status_code, code = 404, "not_found"


class FileTooLarge(MediaError):
    status_code, code = 413, "file_too_large"


class UnsupportedMediaType(MediaError):
    status_code, code = 415, "unsupported_media_type"


class InvalidImage(MediaError):
    status_code, code = 422, "invalid_image"


class DimensionsExceeded(MediaError):
    status_code, code = 422, "image_dimensions_exceeded"


class BadRequest(MediaError):
    status_code, code = 422, "validation_error"


class QuotaFiles(MediaError):
    status_code, code = 429, "quota_files_exceeded"


class QuotaUploads(MediaError):
    status_code, code = 429, "quota_uploads_exceeded"


class StorageUnavailable(MediaError):
    status_code, code = 503, "storage_unavailable"
