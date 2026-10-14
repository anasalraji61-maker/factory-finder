"""Sanitising and spam screening for review / reply text (pure)."""

from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

from ff_rfq.domain.errors import ValidationFailed

_KEEP = {"\n"}
_URL = re.compile(r"(?:[a-z][a-z0-9+.-]{1,10}://|\bwww\s*\.|\b(?:wa|t)\s*\.\s*me\b)", re.I)
_TLDS = (
    "com|net|org|info|biz|io|co|cn|ae|iq|ru|me|ly|shop|xyz|top|app|link|site|online|store|cc|tv|ws|"
    "gl|be|us|uk|de|tk|ml|ga|cf|gq|vip|club|live|pro|dev|page|click|ir|tr|in|pk|sa|eg"
)
_DOMAIN = re.compile(rf"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:{_TLDS})\b", re.I)
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+\s*(?:@|\(at\)|\[at\])\s*[\w-]+", re.I)
_PHONE = re.compile(r"(?:\+?\d[\s().\-_/]*){9,}")


def sanitize(text: str) -> str:
    """Drop control, format (bidi / zero-width) and surrogate characters; normalise newlines; trim."""
    out = []
    for ch in text.replace("\r\n", "\n").replace("\r", "\n"):
        if ch in _KEEP or ch == " ":
            out.append(ch)
        elif unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"):
            continue
        else:
            out.append(ch)
    cleaned = re.sub(r"\n{3,}", "\n\n", "".join(out))
    return cleaned.strip()


def _ascii_digits(text: str) -> str:
    return "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in text)


def detect_contact(text: str) -> str | None:
    """'url' | 'email' | 'phone' when the text carries contact info / links, else None."""
    t = _ascii_digits(unicodedata.normalize("NFKC", text))
    if _URL.search(t) or _DOMAIN.search(t):
        return "url"
    if _EMAIL.search(t):
        return "email"
    if _PHONE.search(t):
        return "phone"
    return None


def clean_text(value: str | None, field: str, max_len: int) -> str | None:
    """Sanitised text or None when empty. 422 ``prohibited_content`` for URLs / emails / phone numbers."""
    if value is None:
        return None
    cleaned = sanitize(value)
    if len(cleaned) > max_len:
        raise ValidationFailed(f"{field} is too long (max {max_len})", code="text_too_long",
                               details={"field": field, "max": max_len})
    if not cleaned:
        return None
    kind = detect_contact(cleaned)
    if kind:
        raise ValidationFailed(f"{field} must not contain links, emails or phone numbers",
                               code="prohibited_content", details={"field": field, "kind": kind})
    return cleaned


def reviewer_display(raw_name: str | None) -> str:
    """'Ahmed Karim' -> 'Ahmed K.'; single name -> as is; unknown / email-like -> 'Verified buyer'."""
    name = sanitize(raw_name or "")
    if not name or "@" in name or detect_contact(name):
        return "Verified buyer"
    parts = name.split()
    first = parts[0][:20]
    if len(parts) == 1:
        return first
    return f"{first} {parts[-1][0].upper()}."


def average(total: int, count: int) -> str | None:
    if count == 0:
        return None
    return format((Decimal(total) / Decimal(count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")
