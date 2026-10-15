"""Simple keyword rules: language detection, buy-intent, product phrase, origin country."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_AR_RE = re.compile(r"[؀-ۿ]")
_MARKS = re.compile(
    "[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e8\u06ea-\u06ed\u0640]"
)
# 1:1 mapping, so offsets in the folded copy equal offsets in the cleaned text
_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"})


def _clean(text: str) -> str:
    """Drop tashkeel/tatweel (display-safe)."""
    return _MARKS.sub("", text)


def _fold(text: str) -> str:
    """Casefold + unify alef/ya/ta-marbuta; same length as ``_clean(text)`` so spans map back."""
    return text.lower().translate(_FOLD)
_LATIN_RE = re.compile(r"[A-Za-z]")

_BUY_AR = (
    "أحتاج",
    "احتاج",
    "أريد",
    "اريد",
    "أبي",
    "ابي",
    "أبحث عن",
    "ابحث عن",
    "مطلوب",
    "شلون أحصل",
    "وين الاقي",
    "وين ألقى",
    "محتاج",
    "نحتاج",
    "أرغب بشراء",
    "للشراء",
    "ابغي",
    "ابغى",
    "أبغي",
    "بدي",
    "عايز",
)
_BUY_EN = (
    "looking for",
    "need ",
    "i need",
    "we need",
    "want to buy",
    "wtb",
    "wanted:",
    "where can i buy",
    "where to buy",
    "in search of",
    "buy ",
)
_ORIGINS = {"CN": ("الصين", "صيني", "china", "chinese")}
_ORIGIN_PHRASE = re.compile(r"\s*(من|from)\s+(الصين|china)\b", re.IGNORECASE)
_LEAD = re.compile(
    "("
    + "|".join(re.escape(_fold(w)) for w in (*_BUY_AR, *_BUY_EN))
    + r"|please|مرحبا|السلام عليكم)\s*",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[.!?؟،,:;\n\r]+")


@dataclass(frozen=True)
class Intent:
    query: str
    origin_country: str | None


def detect_language(text: str, override: str | None = None) -> str:
    if override in ("ar", "en"):
        return override
    ar, lat = len(_AR_RE.findall(text)), len(_LATIN_RE.findall(text))
    return "ar" if ar >= lat and ar > 0 else "en"


def extract_intent(text: str) -> Intent | None:
    """``None`` when the post is not a buy-request."""
    text = _clean(text)
    low = _fold(text)
    if not any(_fold(k) in low for k in (*_BUY_AR, *_BUY_EN)):
        return None
    origin = next(
        (cc for cc, words in _ORIGINS.items() if any(_fold(w) in low for w in words)), None
    )
    head = _PUNCT.split(text.strip())[0]
    # cut leading buy words on the folded copy, keep the user's own spelling for the query
    folded_head = _fold(head)
    cut = 0
    # strip stacked lead words ("hello, I need ..."); skip if folding changed the length
    for _ in range(3 if len(folded_head) == len(head) else 0):
        m = _LEAD.match(folded_head, cut)
        if not m or m.end() == cut:
            break
        cut = m.end()
    phrase = _ORIGIN_PHRASE.sub("", head[cut:]).strip()
    phrase = phrase[:120].strip()
    if len(phrase) < 2:
        return None
    return Intent(query=phrase, origin_country=origin)


def signal_key(text: str, url: str | None) -> str:
    basis = (url or "").strip().casefold().rstrip("/") or re.sub(
        r"\s+", " ", text
    ).strip().casefold()
    return hashlib.sha256(basis.encode()).hexdigest()
