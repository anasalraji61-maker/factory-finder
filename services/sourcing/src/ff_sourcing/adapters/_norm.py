"""Helpers shared by real-adapter normalizers."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from ..domain.models import (
    ListingDetail,
    Location,
    Money,
    MoneyRange,
    SupplierSummary,
)
from ..domain.pricing import normalize_unit, parse_price_text
from ..domain.quality import normalize_currency_code

MAX_IMAGES = 8
_ISO = re.compile(r"^[A-Z]{3}$")


def dec(value: Any, default: str = "0") -> Decimal:
    try:
        d = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return Decimal(default)
    return d if d.is_finite() else Decimal(default)


@dataclass(frozen=True)
class PriceInfo:
    lo: Decimal
    hi: Decimal
    currency: str | None  # None => the text did not say; caller applies its documented default
    unit: str | None = None
    moq: int | None = None


def read_price(value: Any, *, country: str | None = None) -> PriceInfo | None:
    """Parse a provider price value (number or text like 'US $12.5-15 /ton') via the shared pricing parser.

    Returns None for null / empty / non-positive / unparsable prices, never a silent 0.
    """
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if text.startswith(("-", "−")):  # a leading minus is a negative price, not a range separator
        return None
    parsed = parse_price_text(text, country)
    if parsed.price_min is None or parsed.price_max is None:
        return None
    lo, hi = parsed.price_min, parsed.price_max
    if lo <= 0 or not (lo.is_finite() and hi.is_finite()):
        return None
    ccy = parsed.currency if parsed.currency and _ISO.match(parsed.currency) else None
    return PriceInfo(lo=lo, hi=hi, currency=ccy, unit=parsed.unit, moq=parsed.moq)


def to_moq(value: Any) -> int | None:
    """'20 Tons' / '1,000' / 5 / 5.0 -> int > 0, else None."""
    if value is None or isinstance(value, bool):
        return None
    m = re.search(r"\d[\d,]*", str(value))
    if not m:
        return None
    n = int(m.group().replace(",", ""))
    return n if 0 < n < 10**9 else None


def resolve_price(
    *,
    text: Any = None,
    lo: Any = None,
    hi: Any = None,
    currency: Any = None,
    default_currency: str,
    country: str | None = None,
) -> PriceInfo | None:
    """Combine explicit min/max fields and/or price text into one validated range with a currency.

    Currency precedence: explicit currency field > symbol/code found in the price text > default.
    Returns None when no positive price can be read.
    """
    a = read_price(lo, country=country) if lo not in (None, "") else None
    if a is not None:
        b = read_price(hi, country=country) if hi not in (None, "") else None
        base = PriceInfo(a.lo, max(a.lo, b.hi) if b else a.hi, a.currency or (b.currency if b else None))
        if b and b.lo < a.lo:
            base = PriceInfo(b.lo, max(a.hi, b.hi), base.currency)
    else:
        base = read_price(text, country=country) if text not in (None, "") else None
        if base is None:
            return None
    ccy = normalize_currency_code(currency) or base.currency or (default_currency.upper() or None)
    unit = base.unit
    return PriceInfo(base.lo, base.hi, ccy, unit, base.moq)


def clean_unit(value: Any) -> str | None:
    """'件' / 'Pcs' / 'Tons' -> canonical unit via the shared parser; unknown units pass through trimmed."""
    t = norm_name(value)
    if not t:
        return None
    return normalize_unit(t) or t[:30]


def image_list(raw: Any) -> list[str]:
    """Strings, or dicts with url/src, or {'string': [...]} wrappers -> candidate URL strings."""
    if isinstance(raw, dict):
        for k in ("string", "url", "src", "images"):
            if k in raw:
                return image_list(raw[k])
        return []
    if isinstance(raw, str):
        return [raw]
    out: list[str] = []
    if isinstance(raw, (list, tuple)):
        for i in raw:
            out.extend(image_list(i))
    return out


def dig(obj: Any, *path: str) -> Any:
    """Null-safe nested dict lookup: dig(p, 'a', 'b') -> None when any hop is missing/None/not a dict."""
    for k in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def truthy(v: Any) -> bool:
    return str(v).strip().lower() in {"1", "true", "y", "yes", "t"}


def safe_http_url(url: Any) -> str | None:
    """Only absolute http(s) URLs with a host and no embedded credentials; anything else is dropped."""
    if not isinstance(url, str):
        return None
    u = url.strip()
    if not u or len(u) > 2048 or any(c.isspace() or ord(c) < 32 for c in u):
        return None
    try:
        parts = urlsplit(u)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not host or parts.username or parts.password:
        return None
    return u


def safe_image_urls(urls: Any, limit: int = MAX_IMAGES) -> list[str]:
    """https only (no http, protocol-relative, data:, javascript:), de-duplicated, order kept, capped."""
    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, (list, tuple)):
        return []
    out: list[str] = []
    for u in urls:
        ok = safe_http_url(u)
        if ok and urlsplit(ok).scheme.lower() == "https" and ok not in out:
            out.append(ok)
        if len(out) >= limit:
            break
    return out


_COUNTRY_NAMES = {
    "china": "CN", "prc": "CN", "people's republic of china": "CN", "中国": "CN", "hong kong": "HK",
    "taiwan": "TW", "united states": "US", "usa": "US", "germany": "DE", "india": "IN", "vietnam": "VN",
    "turkey": "TR", "japan": "JP", "south korea": "KR", "italy": "IT", "united kingdom": "GB", "uk": "GB",
}


def norm_country(value: Any, default: str = "CN") -> str:
    """ISO alpha-2 only. 'cn' -> CN, 'China' -> CN; anything unrecognised -> default (never truncate 'China' to 'CH')."""
    t = norm_name(value)
    if len(t) == 2 and t.isalpha() and t.isascii():
        return t.upper()
    return _COUNTRY_NAMES.get(t.casefold(), default)


def norm_name(name: Any) -> str:
    """NFKC, collapse whitespace, strip control chars; non-strings become ''."""
    if name is None or isinstance(name, (dict, list)):
        return ""
    s = unicodedata.normalize("NFKC", str(name))
    s = "".join(" " if unicodedata.category(c).startswith("C") else c for c in s)
    return " ".join(s.split())[:200]


def supplier_key(native_id: Any, name: str, fallback: str = "") -> str:
    """Stable supplier id token: provider id, else a slug of the name, else per-listing ``unknown-<fallback>``
    (never one shared bucket, so unrelated anonymous sellers are not merged)."""
    raw = norm_name(native_id) if native_id not in (None, "None") else ""
    if not raw:
        slug = re.sub(r"[^\w]+", "-", name.casefold()).strip("-")[:60]
        raw = f"n-{slug}" if slug else f"unknown-{fallback}"
    return re.sub(r"[^\w.:\-]+", "-", raw).strip("-") or "unknown"


def build_listing(
    *,
    source: str,
    native_id: str,
    title: str,
    price_min: Any,
    price_max: Any,
    currency: str,
    supplier_native_id: str,
    supplier_name: str,
    country: str = "CN",
    city: str | None = None,
    kind: str = "product",
    url: str | None = None,
    images: list[str] | None = None,
    moq: int | None = None,
    unit: str | None = None,
    verified: bool = False,
) -> ListingDetail:
    lo, hi = dec(price_min), dec(price_max if price_max not in (None, "") else price_min)
    if hi < lo:
        lo, hi = hi, lo
    if lo <= 0:
        raise ValueError("no usable price")  # callers skip the item; a 0 price must never reach buyers
    currency = str(currency or "").strip().upper()
    if not _ISO.match(currency):
        raise ValueError("bad currency")
    supplier_name = norm_name(supplier_name)
    title = norm_name(title)[:300]
    if not title:
        raise ValueError("no title")
    moq = to_moq(moq)
    city = norm_name(city) or None
    country = norm_country(country)
    loc = Location(country_code=country, city=city)
    return ListingDetail(
        id=f"lst_{source}_{native_id}",
        source=source,
        source_url=safe_http_url(url),
        kind=kind,  # type: ignore[arg-type]
        title=title,
        images=safe_image_urls(images),
        unit=unit,
        moq=moq,
        price=MoneyRange(
            min=Money(amount=lo, currency=currency), max=Money(amount=hi, currency=currency)
        ),
        supplier=SupplierSummary(
            id=f"sup_{source}_{supplier_key(supplier_native_id, supplier_name, native_id)}",
            name=supplier_name or "Unknown supplier",
            location=loc,
            verified=verified,
        ),
        origin=loc,
    )
