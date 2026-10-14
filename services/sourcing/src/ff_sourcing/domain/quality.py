"""Data-quality normalization for listings from external feeds (pure, deterministic, no I/O).

  * detect_currency  - ISO code / symbol / word -> ISO 4217 code (ambiguous symbols are explicit)
  * price_is_sane    - positive, ordered, within configured bounds, not an absurd range
  * dedupe_listings  - same supplier + near-identical title (token-set similarity) -> keep best one
Money stays Decimal (CLAUDE.md rule 8).
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal
from difflib import SequenceMatcher

from .models import Listing

# Longest/most specific first. "¥" alone is ambiguous (CNY/JPY): default CNY, override via aliases.
DEFAULT_CURRENCY_TOKENS: dict[str, str] = {
    "US$": "USD", "USD": "USD", "$": "USD", "DOLLAR": "USD",
    "EUR": "EUR", "€": "EUR", "EURO": "EUR",
    "GBP": "GBP", "£": "GBP",
    "CNY": "CNY", "RMB": "CNY", "CN¥": "CNY", "元": "CNY", "¥": "CNY", "￥": "CNY",
    "JPY": "JPY", "JP¥": "JPY", "円": "JPY",
    "IQD": "IQD", "د.ع": "IQD",
    "AED": "AED", "INR": "INR", "₹": "INR", "TRY": "TRY", "₺": "TRY", "KRW": "KRW", "₩": "KRW",
}
_ISO = re.compile(r"^[A-Z]{3}$")
_STOP = {"the", "a", "an", "for", "and", "with", "of", "new", "hot", "sale", "high", "quality"}


def detect_currency(
    text: object, aliases: dict[str, str] | None = None, default: str | None = None
) -> str | None:
    """Find a currency in free text ('US $12.5', 'RMB 80', '120 元', 'eur')."""
    s = str(text or "").strip()
    if not s:
        return default
    table = {**DEFAULT_CURRENCY_TOKENS, **{k.upper(): v.upper() for k, v in (aliases or {}).items()}}
    up = s.upper()
    for tok in sorted(table, key=len, reverse=True):
        t = tok.upper()
        if t.isascii() and t.isalpha():
            if re.search(rf"(?<![A-Z]){re.escape(t)}(?![A-Z])", up):
                return table[tok]
        elif t in up:
            return table[tok]
    return default


def normalize_currency_code(
    value: object, aliases: dict[str, str] | None = None, default: str | None = None
) -> str | None:
    code = detect_currency(value, aliases)
    if code:
        return code
    v = str(value or "").strip().upper()
    return v if _ISO.match(v) else default


def price_is_sane(
    lo: Decimal,
    hi: Decimal,
    min_price: Decimal = Decimal("0.0001"),
    max_price: Decimal = Decimal("100000000"),
    max_ratio: Decimal = Decimal("1000"),
) -> bool:
    if lo <= 0 or hi < lo:
        return False
    if lo < min_price or hi > max_price:
        return False
    return hi / lo <= max_ratio


def _title_tokens(title: str) -> list[str]:
    t = unicodedata.normalize("NFKC", title).lower()
    toks = re.findall(r"[\w一-鿿]+", t)
    return sorted(w for w in toks if w not in _STOP)


def title_similarity(a: str, b: str) -> float:
    """0..1, order-insensitive (sorted tokens) so 'PP granules virgin' ~ 'virgin PP granules'."""
    ta, tb = " ".join(_title_tokens(a)), " ".join(_title_tokens(b))
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb).ratio()


def _supplier_key(item: Listing) -> str:
    name = unicodedata.normalize("NFKC", item.supplier.name).lower()
    name = re.sub(r"[^\w一-鿿]+", " ", name).strip()
    return name or item.supplier.id


def _quality(item: Listing) -> tuple:
    # prefer more images, a source url, then lower price, then id (deterministic)
    return (-len(item.images), item.source_url is None, item.price.min.amount, item.id)


def dedupe_listings(items: list[Listing], threshold: float = 0.9) -> list[Listing]:
    """Drop near-duplicates from the SAME supplier; order of survivors follows first appearance."""
    kept: list[Listing] = []
    for item in items:
        sk = _supplier_key(item)
        dup = next(
            (
                i
                for i, k in enumerate(kept)
                if _supplier_key(k) == sk
                and k.price.min.currency == item.price.min.currency
                and title_similarity(k.title, item.title) >= threshold
            ),
            None,
        )
        if dup is None:
            kept.append(item)
        elif _quality(item) < _quality(kept[dup]):
            kept[dup] = item
    return kept
