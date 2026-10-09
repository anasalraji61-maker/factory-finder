"""Gateway error hierarchy.

Every error maps to the standard body ``{"error": {"code", "message", "details"}}``.
The HTTP status lives on the class so the web layer can render any error uniformly.
"""

from typing import Any, ClassVar

BEARER_REALM = 'Bearer realm="factory-finder"'
BEARER_INVALID_TOKEN = 'Bearer realm="factory-finder", error="invalid_token"'


class GatewayError(Exception):
    status_code: ClassVar[int] = 500
    code: ClassVar[str] = "internal_error"
    default_message: ClassVar[str] = "Internal server error"
    default_headers: ClassVar[dict[str, str]] = {}

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details: dict[str, Any] = dict(details or {})
        self.headers: dict[str, str] = {**self.default_headers, **(headers or {})}
        super().__init__(self.message)


class InvalidPath(GatewayError):
    status_code = 400
    code = "invalid_path"
    default_message = "Request path is not allowed"


class ValidationFailed(GatewayError):
    status_code = 422
    code = "validation_error"
    default_message = "Request validation failed"

    @classmethod
    def for_field(cls, field: str, message: str) -> "ValidationFailed":
        return cls(
            details={
                "errors": [
                    {"field": field, "location": "body", "message": message, "type": "value_error"}
                ]
            }
        )


class AuthenticationRequired(GatewayError):
    status_code = 401
    code = "authentication_required"
    default_message = "A valid access token is required"
    default_headers = {"WWW-Authenticate": BEARER_REALM}


class InvalidToken(GatewayError):
    status_code = 401
    code = "invalid_token"
    default_message = "The token is invalid"
    default_headers = {"WWW-Authenticate": BEARER_INVALID_TOKEN}


class TokenExpired(GatewayError):
    status_code = 401
    code = "token_expired"
    default_message = "The token has expired"
    default_headers = {"WWW-Authenticate": BEARER_INVALID_TOKEN}


class InvalidCredentials(GatewayError):
    status_code = 401
    code = "invalid_credentials"
    default_message = "Incorrect email/phone or password"
    default_headers = {"WWW-Authenticate": BEARER_REALM}


class AccountDisabled(GatewayError):
    status_code = 403
    code = "account_disabled"
    default_message = "This account is disabled"


class AccountExists(GatewayError):
    status_code = 409
    code = "account_exists"
    default_message = "An account with these details already exists"

    def __init__(self, field: str | None = None) -> None:
        message = f"An account with this {field} already exists" if field else None
        super().__init__(message, details={"field": field} if field else {})
        self.field = field


class RateLimited(GatewayError):
    status_code = 429
    code = "rate_limited"
    default_message = "Too many requests, please retry later"

    def __init__(self, retry_after_seconds: int, limit: int) -> None:
        super().__init__(
            details={"retry_after_seconds": retry_after_seconds},
            headers={
                "Retry-After": str(retry_after_seconds),
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": "0",
            },
        )


class PayloadTooLarge(GatewayError):
    status_code = 413
    code = "payload_too_large"
    default_message = "Request body is too large"


class UpstreamUnavailable(GatewayError):
    status_code = 502
    code = "upstream_unavailable"
    default_message = "The upstream service is unavailable"

    def __init__(
        self, upstream: str, message: str | None = None, *, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(
            message or f"The {upstream} service is unavailable",
            details={"upstream": upstream, **(details or {})},
        )
        self.upstream = upstream


class UpstreamTimeout(GatewayError):
    status_code = 504
    code = "upstream_timeout"
    default_message = "The upstream service did not respond in time"

    def __init__(self, upstream: str) -> None:
        super().__init__(
            f"The {upstream} service did not respond in time", details={"upstream": upstream}
        )
        self.upstream = upstream
