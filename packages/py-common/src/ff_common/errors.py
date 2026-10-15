"""Error envelope helpers matching contracts/schemas/common.schema.json#/$defs/Error."""

from __future__ import annotations

from typing import Any


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    if not code or not message:
        raise ValueError("code and message are required")
    return {"error": {"code": code, "message": message, "details": dict(details or {})}}


def is_error_body(obj: Any) -> bool:
    e = obj.get("error") if isinstance(obj, dict) else None
    return isinstance(e, dict) and isinstance(e.get("code"), str) and isinstance(e.get("message"), str) \
        and isinstance(e.get("details", {}), dict)  # fmt: skip


_STATUS_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict",
                 422: "validation_error", 429: "rate_limited", 503: "unavailable"}  # fmt: skip


def code_for_status(status: int) -> str:
    return _STATUS_CODES.get(status, "internal_error" if status >= 500 else "error")
