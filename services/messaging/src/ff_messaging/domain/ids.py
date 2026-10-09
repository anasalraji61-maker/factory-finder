"""Identifier helpers: ``<prefix>_<ULID>`` (time-ordered, 26 Crockford base32 chars)."""

import re
import secrets
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

CONVERSATION_PREFIX = "conv"
MESSAGE_PREFIX = "msg"

# Opaque ids coming from other services (users, listings, requests, offers, deals).
EXTERNAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}$"
USER_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}$"
_USER_ID_RE = re.compile(USER_ID_PATTERN)


def new_ulid() -> str:
    value = (time.time_ns() // 1_000_000) << 80 | secrets.randbits(80)
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    return f"{prefix}_{new_ulid()}"


def is_valid_user_id(value: str) -> bool:
    return bool(_USER_ID_RE.fullmatch(value))
