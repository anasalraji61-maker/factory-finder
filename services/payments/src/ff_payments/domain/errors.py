"""Domain errors.

Every error carries a stable snake_case ``code`` (part of the API contract) and the HTTP status the
API layer answers with. The API turns them into ``{"error": {"code", "message", "details"}}``.
"""

from collections.abc import Iterable
from typing import Any


class DomainError(Exception):
    """Base class for expected, user-facing failures."""

    status_code: int = 400
    default_code: str = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.details: dict[str, Any] = details or {}


class Unauthenticated(DomainError):
    status_code = 401
    default_code = "unauthenticated"


class Forbidden(DomainError):
    status_code = 403
    default_code = "forbidden"


class NotFound(DomainError):
    status_code = 404
    default_code = "not_found"


class Conflict(DomainError):
    status_code = 409
    default_code = "conflict"


class InvalidTransition(Conflict):
    """A state-machine transition that is not allowed from the current status."""

    def __init__(
        self,
        entity: str,
        current: str,
        action: str,
        *,
        allowed: Iterable[str] = (),
        entity_id: str | None = None,
    ) -> None:
        details: dict[str, Any] = {
            "entity": entity,
            "status": str(current),
            "action": str(action),
            "allowed_actions": sorted(str(item) for item in allowed),
        }
        if entity_id is not None:
            details["id"] = entity_id
        super().__init__(
            f"A {entity} in status '{current}' does not allow '{action}'",
            code=f"invalid_{entity}_transition",
            details=details,
        )
        self.entity = entity
        self.current = str(current)
        self.action = str(action)


class ValidationFailed(DomainError):
    status_code = 422
    default_code = "validation_error"


class UnsupportedCurrency(ValidationFailed):
    default_code = "unsupported_currency"


class UpstreamUnavailable(DomainError):
    """Another Factory Finder service failed or answered with something unusable."""

    status_code = 502
    default_code = "upstream_unavailable"
