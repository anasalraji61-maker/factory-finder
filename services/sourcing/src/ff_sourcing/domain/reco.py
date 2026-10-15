"""Similar-listing and recommendation scoring (pure, deterministic, explainable; no user data)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel

from .models import Listing, ListingDetail
from .search import mid_price
from .text import tokens

MAX_CANDIDATES = 300  # candidates scored per request
TRUST_STAGE = 60  # candidates that get a trust lookup (top by pre-score)
MIN_SCORE = 0.25
PER_SUPPLIER_CAP = 3  # diversity in /v1/recommendations
_GENERIC_SPEC_KEYS = {"hs code", "condition", "incoterm", "unit weight (kg)", "unit volume (m3)"}
_TRUST_W = {"green": 0.10, "yellow": 0.03, "red": -0.25, "unknown": 0.0}

REASONS: dict[str, tuple[str, str]] = {
    "same_category": ("Same category", "نفس الفئة"),
    "similar_title": ("Similar product", "منتج مشابه"),
    "shared_specs": ("Shares material/specifications", "يشترك بالمواد/المواصفات"),
    "similar_price": ("Similar price range", "نطاق سعر مماثل"),
    "same_condition": ("Same condition", "نفس الحالة"),
    "different_supplier": ("From a different supplier", "من مورّد مختلف"),
    "same_supplier": ("From the same supplier", "من نفس المورّد"),
    "trusted_supplier": ("Highly trusted supplier", "مورّد موثوق جداً"),
    "verified_supplier": ("Verified supplier", "مورّد موثّق"),
    "origin_country_match": ("Ships from your preferred country", "يُشحن من البلد المفضّل"),
    "because_viewed": ("Similar to a listing you viewed", "مشابه لمنتج شاهدته"),
    "top_trusted": ("Top trusted supplier", "من أكثر الموردين موثوقية"),
}


class Reason(BaseModel):
    code: str
    en: str
    ar: str
    ref_listing_id: str | None = None


class Recommended(BaseModel):
    listing: Listing
    score: float
    reasons: list[Reason]


def reason(code: str, ref: str | None = None) -> Reason:
    en, ar = REASONS[code]
    return Reason(code=code, en=en, ar=ar, ref_listing_id=ref)


@dataclass(frozen=True)
class Features:
    id: str
    kind: str
    category: str | None
    condition: str
    title_tokens: frozenset[str]
    spec_tokens: frozenset[str]
    mid: Decimal
    currency: str
    supplier_id: str
    country: str | None


def features(item: Listing) -> Features:
    title = set(tokens(item.title)) | set(tokens(item.title_ar or ""))
    specs: set[str] = set()
    for k, v in (getattr(item, "specs", None) or {}).items():
        if k.strip().lower() not in _GENERIC_SPEC_KEYS:
            specs |= set(tokens(str(v)))
    title = {t for t in title if len(t) > 1}
    specs = {t for t in specs if len(t) > 1 and not t.isdigit()}
    return Features(
        id=item.id,
        kind=item.kind,
        category=item.category,
        condition=item.condition,
        title_tokens=frozenset(title),
        spec_tokens=frozenset(specs),
        mid=mid_price(item),
        currency=item.price.min.currency,
        supplier_id=item.supplier.id,
        country=(item.origin.country_code if item.origin else item.supplier.location.country_code),
    )


def _dice(a: frozenset[str], b: frozenset[str]) -> float:
    return 2 * len(a & b) / (len(a) + len(b)) if a and b else 0.0


def similarity(ref: Features, cand: Features, item: Listing) -> tuple[float, list[Reason]]:
    """Score in [0, 1] plus reason codes. 0 when not eligible (other kind, same listing, too little overlap)."""
    if cand.id == ref.id or cand.kind != ref.kind:
        return 0.0, []
    score, why = 0.0, []
    same_cat = bool(ref.category) and ref.category == cand.category
    ref_all, cand_all = ref.title_tokens | ref.spec_tokens, cand.title_tokens | cand.spec_tokens
    text = _dice(ref_all, cand_all)
    if not same_cat and text < 0.2:
        return 0.0, []
    if same_cat:
        score += 0.30
        why.append(reason("same_category"))
    if text > 0:
        score += 0.30 * min(1.0, text * 1.5)
        if ref.spec_tokens & cand.spec_tokens:
            why.append(reason("shared_specs"))
        elif len(ref.title_tokens & cand.title_tokens) >= 1 and text >= 0.2:
            why.append(reason("similar_title"))
    if ref.currency == cand.currency and ref.mid > 0 and cand.mid > 0:
        dist = abs(math.log(float(cand.mid / ref.mid))) / math.log(2)  # 0 = equal, 1 = 2x apart
        if dist < 1:
            score += 0.15 * (1 - dist)
            why.append(reason("similar_price"))
    if ref.condition == cand.condition:
        score += 0.05
        why.append(reason("same_condition"))
    if ref.supplier_id != cand.supplier_id:
        score += 0.08
        why.append(reason("different_supplier"))
    else:
        score -= 0.08
        why.append(reason("same_supplier"))
    band = item.supplier.trust_band
    score += _TRUST_W.get(band, 0.0)
    if band == "green":
        why.append(reason("trusted_supplier"))
    if item.supplier.verified:
        score += 0.02
        why.append(reason("verified_supplier"))
    return max(0.0, min(1.0, score)), why


def rank_key(r: Recommended) -> tuple[float, str]:
    return (-r.score, r.listing.id)


def as_listing(item: ListingDetail) -> Listing:
    return Listing(**{k: getattr(item, k) for k in Listing.model_fields})
