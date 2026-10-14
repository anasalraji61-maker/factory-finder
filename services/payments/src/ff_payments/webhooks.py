"""HMAC-SHA256 webhook signatures: header ``X-FF-Signature: t=<unix>,v1=<hex>`` over ``"<t>.<raw body>"``."""

from __future__ import annotations

import hashlib
import hmac

from ff_payments.domain.errors import DomainError


class InvalidSignature(DomainError):
    status_code = 401
    default_code = "invalid_signature"


def sign(secret: str, body: bytes, timestamp: int) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def verify(secret: str, body: bytes, header: str | None, *, now_ts: int, tolerance: int) -> None:
    """Raises InvalidSignature (401) on a missing/malformed/stale/wrong signature. Constant-time compare."""
    if not header or len(header) > 512:
        raise InvalidSignature("Missing signature")
    ts: int | None = None
    candidates: list[str] = []
    for part in header.split(","):
        k, _, v = part.strip().partition("=")
        if k == "t" and v.isdigit():
            ts = int(v)
        elif k == "v1":
            candidates.append(v)
    if ts is None or not candidates:
        raise InvalidSignature("Malformed signature")
    expected = sign(secret, body, ts).split("v1=", 1)[1]
    ok = False
    for c in candidates:  # no early exit: every candidate is compared
        ok |= hmac.compare_digest(c.encode(), expected.encode())
    if not ok:
        raise InvalidSignature("Bad signature")
    if abs(now_ts - ts) > tolerance:
        raise InvalidSignature("Stale timestamp", code="stale_timestamp")
