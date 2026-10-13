"""Domain errors: stable snake_case ``code`` + HTTP status; the API renders the error body."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status_code = 400
    default_code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.details = details or {}


class Unauthenticated(DomainError):
    status_code = 401
    default_code = "unauthenticated"


class NotFound(DomainError):
    status_code = 404
    default_code = "not_found"


class Conflict(DomainError):
    status_code = 409
    default_code = "conflict"


class InvalidReference(DomainError):
    status_code = 422
    default_code = "invalid_reference"


class RefreshThrottled(DomainError):
    status_code = 429
    default_code = "refresh_throttled"

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            f"Refreshed too recently; retry in {retry_after_seconds}s",
            details={"retry_after_seconds": retry_after_seconds},
        )
        self.retry_after_seconds = retry_after_seconds
