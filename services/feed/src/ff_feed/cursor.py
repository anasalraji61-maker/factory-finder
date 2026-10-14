"""Opaque keyset cursors: urlsafe-base64 JSON ``{k: kind, t: iso-time, i: id[, s: score]}``."""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import UTC, datetime

from ff_feed.errors import Invalid

MAX_LEN = 300
_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")


def encode(kind: str, created_at: datetime, ident: str, score: int | None = None) -> str:
    d: dict = {"k": kind, "t": created_at.astimezone(UTC).isoformat(), "i": ident}
    if score is not None:
        d["s"] = score
    raw = json.dumps(d, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode(cursor: str, allowed: tuple[str, ...]) -> dict:
    """Returns {k, t (aware datetime), i, s (int|None)}; any malformed cursor is a 422."""
    bad = Invalid("Invalid cursor", code="invalid_cursor")
    if not cursor or len(cursor) > MAX_LEN:
        raise bad
    try:
        d = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        t = datetime.fromisoformat(d["t"])
        ok = (
            isinstance(d, dict)
            and d.get("k") in allowed
            and isinstance(d["i"], str)
            and _ID.match(d["i"])
            and t.tzinfo is not None
        )
        s = d.get("s")
        if s is not None and (not isinstance(s, int) or isinstance(s, bool)):
            ok = False
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeDecodeError):
        raise bad from None
    if not ok:
        raise bad
    if (d["k"] == "t") != (s is not None):
        raise bad
    return {"k": d["k"], "t": t.astimezone(UTC), "i": d["i"], "s": s}
