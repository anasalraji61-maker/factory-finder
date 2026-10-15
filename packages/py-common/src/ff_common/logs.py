"""Log redaction and structured formatting (same JSON/text shapes as the per-service obs.py)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

MASK = "[REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"(authorization|password|passwd|secret|token|api[-_]?key|cookie|set-cookie|credential)", re.I
)
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]+")
_KV = re.compile(r"(?i)\b(password|passwd|secret|token|api[-_]?key|access_token|refresh_token)=([^\s&\"']+)")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*")
_EMAIL = re.compile(r"([A-Za-z0-9._%+\-])([A-Za-z0-9._%+\-]*)@([A-Za-z0-9\-]+)(\.[A-Za-z0-9.\-]+)")
_CTRL = re.compile(r"[\x00-\x1f\x7f  ]")


def mask_email(m: re.Match[str]) -> str:
    return f"{m.group(1)}***@{m.group(3)[0]}***{m.group(4)}"


def redact_text(s: str) -> str:
    s = _BEARER.sub(lambda m: f"{m.group(1)} {MASK}", s)
    s = _JWT.sub(MASK, s)
    s = _KV.sub(lambda m: f"{m.group(1)}={MASK}", s)
    return _EMAIL.sub(mask_email, s)


def redact(obj: Any) -> Any:
    """Deep-copy with sensitive keys masked and strings scrubbed."""
    if isinstance(obj, Mapping):
        return {k: (MASK if isinstance(k, str) and _SENSITIVE_KEY.search(k) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


def format_line(data: Mapping[str, Any], level: str = "INFO", fmt: str = "json", now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    clean = {k: v for k, v in redact(dict(data)).items() if v is not None}
    if fmt == "text":
        rest = " ".join(f"{k}={_CTRL.sub(' ', str(v))}" for k, v in clean.items())
        return f"{now.isoformat(timespec='seconds')} {level} {rest}"
    return json.dumps({"ts": now.isoformat(timespec="milliseconds"), "level": level, **clean},
                      separators=(",", ":"), ensure_ascii=False)  # fmt: skip
