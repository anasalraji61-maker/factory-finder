"""Domain errors. The API layer maps each class to an HTTP status / WebSocket close code."""

from collections.abc import Mapping
from typing import Any


class MessagingError(Exception):
    """Base class: carries a stable snake_case ``code`` and a human-readable message."""

    code: str = "messaging_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details: dict[str, Any] = dict(details or {})


class BadRequestError(MessagingError):
    code = "bad_request"


class InvalidInputError(MessagingError):
    code = "validation_error"


class UnauthenticatedError(MessagingError):
    code = "unauthenticated"


class ForbiddenError(MessagingError):
    code = "forbidden"


class NotFoundError(MessagingError):
    code = "not_found"


class RateLimitedError(MessagingError):
    code = "rate_limited"

    def __init__(self, message: str, *, retry_after_seconds: float) -> None:
        super().__init__(
            message,
            details={"retry_after_seconds": round(max(retry_after_seconds, 0.0), 3)},
        )
        self.retry_after_seconds = max(retry_after_seconds, 0.0)
