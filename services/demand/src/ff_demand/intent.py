"""Simple keyword rules: language detection, buy-intent, product phrase, origin country."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

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
    "ودي",
    "ابغا",
    "بغيت",
    "نبي",
    "نبغي",
    "محتاجين",
    "مطلوب",
    "اشتري",
    "أشتري",
    "ممكن اشتري",
    "عندي طلب",
    "اريد شراء",
)
_BUY_ZH = ("求购", "想买", "想要购买", "需要采购", "采购", "寻找", "找货源", "求推荐供应商", "需要")
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
_SELL = re.compile(
    r"(?i)\b(for sale|wts|we (supply|sell|offer|are (a )?(manufacturer|factory|supplier))|"
    r"our (factory|products)|special offer|discount|dm me to (buy|order)|contact us|"
    r"buy one get one|click (here|the link))\b|للبيع|نبيع|نوفر لكم|عرض خاص|خصم|تواصل معنا|"
    r"اتصل بنا|出售|供应|厂家直销|我们是"
)
_NEGATED = re.compile(
    r"(?i)\b(no need|not looking for|don'?t need|do not need|not interested|"
    r"don'?t buy|never buy)\b|لا احتاج|لا أحتاج|ما احتاج|ما ابي|ما اريد|لا اريد|لا أريد|"
    r"不需要|不想买"
)
_REPEAT = re.compile(r"(.)\1{9,}")
_ORIGINS = {"CN": ("الصين", "صيني", "china", "chinese", "中国")}
_ORIGIN_PHRASE = re.compile(r"\s*(من|from)\s+(الصين|china)\b", re.IGNORECASE)
_LEAD = re.compile(
    "("
    + "|".join(re.escape(_fold(w)) for w in (*_BUY_AR, *_BUY_EN, *_BUY_ZH))
    + r"|please|مرحبا|السلام عليكم)\s*",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[.!?؟،,:;\n\r]+")


def _kw_re(words: tuple[str, ...], bounded: bool) -> re.Pattern[str]:
    alt = "|".join(re.escape(_fold(w.strip())) for w in words)
    return re.compile(rf"(?<!\w)(?:{alt})(?!\w)" if bounded else alt)


_BUY_WORD = _kw_re((*_BUY_AR, *_BUY_EN), True)
_BUY_WORD_ZH = _kw_re(_BUY_ZH, False)


def _has_buy_word(low: str) -> bool:
    """Whole-word match (so "ودي" does not fire inside "موديل", "buy" not inside "buyer")."""
    return bool(_BUY_WORD.search(low) or _BUY_WORD_ZH.search(low))


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
    if not _has_buy_word(low):
        return None
    # spam / sellers / negated or promotional text are not purchase requests
    if _SELL.search(text) or _NEGATED.search(text) or _REPEAT.search(text):
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


_NONWORD = re.compile(r"[^\w\u4e00-\u9fff]+")


_TRACK = re.compile(r"(?i)^(utm_\w+|fbclid|gclid|igshid|ref|ref_src)$")


def _norm_url(url: str) -> str:
    """Host+path+content query; fragments and tracking params are dropped."""
    p = urlsplit(url.strip())
    q = "&".join(
        sorted(kv for kv in p.query.split("&") if kv and not _TRACK.match(kv.split("=")[0]))
    )
    return f"{(p.hostname or '').casefold()}{p.path.rstrip('/')}?{q}".casefold()


def signal_key(text: str, url: str | None) -> str:
    basis = _norm_url(url) if (url or "").strip() else ""
    if not basis:
        basis = _NONWORD.sub(" ", _fold(_clean(text))).strip()
    return hashlib.sha256(basis.encode()).hexdigest()
