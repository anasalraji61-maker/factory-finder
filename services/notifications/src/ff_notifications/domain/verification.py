"""Digest e-mail ownership proof: code hashing, masking, state (pure, no I/O)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import datetime

CODE_TTL_SECONDS = 15 * 60
MAX_ATTEMPTS = 5
LOCK_SECONDS = 60 * 60
MAX_SENDS_PER_HOUR = 3
SEND_WINDOW_SECONDS = 60 * 60


@dataclass(frozen=True, slots=True)
class Verification:
    owner_id: str
    email: str | None = None  # the pending address the code was sent to
    salt: str = ""
    code_hash: str = ""
    expires_at: datetime | None = None
    attempts: int = 0
    locked_until: datetime | None = None
    sends: tuple[datetime, ...] = field(default_factory=tuple)  # send times, last hour


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def new_salt() -> str:
    return secrets.token_hex(16)


def hash_code(salt: str, owner_id: str, email: str, code: str) -> str:
    """HMAC-SHA256 keyed by the per-record salt, bound to the owner and the address."""
    msg = f"{owner_id}\x00{email.lower()}\x00{code}".encode()
    return hmac.new(salt.encode(), msg, hashlib.sha256).hexdigest()


def code_matches(v: Verification, code: str) -> bool:
    """Constant-time comparison of the candidate against the stored hash."""
    if not v.email or not v.salt or not v.code_hash:
        # still burn the same work so absent/present state is not timing-distinguishable
        hmac.compare_digest(hash_code("x", v.owner_id, "x@x", code), "0" * 64)
        return False
    return hmac.compare_digest(hash_code(v.salt, v.owner_id, v.email, code), v.code_hash)


def mask_email(email: str | None) -> str | None:
    """``alice@example.com`` -> ``a***@e***.com``."""
    if not email or "@" not in email:
        return None
    local, _, domain = email.rpartition("@")
    name, dot, tld = domain.rpartition(".")
    if not dot:
        name, tld = domain, ""
    return f"{local[:1]}***@{name[:1]}***{dot}{tld}"
