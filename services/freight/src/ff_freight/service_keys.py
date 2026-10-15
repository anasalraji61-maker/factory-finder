"""Pure helpers: duplicate-detection key, attachment URL validation, profile completeness."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from ff_freight.moderation import normalize

MAX_ATTACHMENTS = 5
_BAD_SUFFIX = (".local", ".internal", ".localhost", ".lan", ".home", ".corp")


def name_key(company_name: str, country_code: str) -> str:
    """Case, diacritic, whitespace, punctuation and Arabic/Latin-digit insensitive company key."""
    return f"{country_code}:{' '.join(normalize(company_name).split())}"[:160]


def check_attachment_url(raw: str) -> str:
    """Return the cleaned URL or raise ValueError. https only, public hostname, no credentials."""
    u = raw.strip()
    if not u or len(u) > 500 or any(ord(ch) < 33 or ord(ch) == 127 for ch in u):
        raise ValueError("attachment URLs must be 1-500 characters without spaces or control characters")
    try:
        p = urlsplit(u)
        port = p.port
        host = (p.hostname or "").lower().rstrip(".")
    except ValueError:
        raise ValueError("attachment URL is malformed") from None
    if p.scheme != "https":
        raise ValueError("attachment URLs must use https")
    if p.username or p.password:
        raise ValueError("attachment URLs must not contain credentials")
    if port not in (None, 443):
        raise ValueError("attachment URLs must use the default https port")
    try:
        ipaddress.ip_address(host)
        raise ValueError("attachment URLs must use a hostname, not an IP address")
    except ValueError as exc:
        if "hostname" in str(exc):
            raise
    if "." not in host or host == "localhost" or host.endswith(_BAD_SUFFIX):
        raise ValueError("attachment URL host is not public")
    return u


_WEIGHTS = (
    ("company_name", 10), ("country_code", 10), ("description", 20), ("lanes", 20),
    ("modes", 10), ("incoterms", 10), ("certifications", 20),
)  # fmt: skip


def completeness(*, company_name, country_code, description, lanes, modes, incoterms, certifications) -> dict:
    """Profile completeness 0-100 with the list of missing fields (sums to exactly 100)."""
    vals = {
        "company_name": bool(company_name and company_name.strip()),
        "country_code": bool(country_code),
        "description": bool(description and len(description.strip()) >= 30),
        "lanes": bool(lanes), "modes": bool(modes), "incoterms": bool(incoterms),
        "certifications": bool(certifications),
    }  # fmt: skip
    score = sum(w for k, w in _WEIGHTS if vals[k])
    return {"score": score, "missing": [k for k, _ in _WEIGHTS if not vals[k]]}
