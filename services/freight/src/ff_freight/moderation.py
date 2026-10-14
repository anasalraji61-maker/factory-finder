"""Prohibited-content screening for free text (requests, quotes, profiles, ratings) (pure; one bundled data file).

A trimmed copy of services/sourcing's ``domain/moderation.py`` (services never import each other's
internals). Flags (a) contact details / off-platform links in free text, so buyers and sellers talk
in-app, and (b) banned goods from ``data/prohibited_goods.json`` (Arabic + English). Reasons name the
*kind* of problem and the field, never the matched text or the keyword that tripped it.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

REPORT_REASONS = (
    "prohibited_item",
    "counterfeit",
    "scam_or_fraud",
    "misleading",
    "contact_info",
    "offensive",
    "spam",
    "other",
)

_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e8\u06ea-\u06ed\u0640]")
_ARABIC_MAP = str.maketrans(
    {
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي",
        "گ": "ك", "چ": "ج", "پ": "ب", "ڤ": "ف", "ک": "ك", "ی": "ي", "ہ": "ه",
        **{chr(0x0660 + i): str(i) for i in range(10)},
        **{chr(0x06F0 + i): str(i) for i in range(10)},
    }
)  # fmt: skip
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)
_CJK = re.compile(r"([\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])")


def normalize(text: str) -> str:
    """Lowercase, strip diacritics/tatweel/accents, unify alef/yaa/taa-marbuta, ASCII digits."""
    text = unicodedata.normalize("NFKD", text or "").lower()
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = _DIACRITICS.sub("", text).translate(_ARABIC_MAP)
    text = _CJK.sub(r" \1 ", text)
    return _NON_WORD.sub(" ", text).strip()


_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_TLDS = (
    "com|net|org|info|biz|io|co|me|ly|cc|top|xyz|shop|store|site|online|app|link|ru|tk|cn|iq|ae|sa|tr|uk|ir|eg"
)
_URL = re.compile(
    rf"(?:https?://|ftp://|www\.)\S+|(?<![\w.@-])(?:[a-z0-9-]+\.)+(?:{_TLDS})(?![\w-])|\bdot\s*com\b|نقطة\s*كوم",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+\s*(?:@|\[at\]|\(at\))\s*[\w-]+(?:\s*(?:\.|\[dot\]|\(dot\))\s*[\w-]+)+", re.IGNORECASE)
_PHONE = re.compile(r"(?<![\w.])\+?\(?\d[\d\s\-().]{6,}\d(?!\w)")
_HANDLE = re.compile(
    r"(?<![\w@])@[a-z0-9_.]{3,}|"
    r"\b(?:whats\s*app|wechat|weixin|telegram|viber|skype|snapchat|signal\s+app|line\s+id|imo)\b|"
    r"واتس\s*اب|واتساب|وتساب|تلكرام|تليجرام|تيليجرام|فايبر|سناب\s*شات|سناب|ويشات|微信",
    re.IGNORECASE,
)
_MIN_PHONE_DIGITS = 9

CONTACT_KINDS = {
    "contact_url": "a web link",
    "contact_email": "an email address",
    "contact_phone": "a phone number",
    "contact_handle": "a messaging-app or social handle",
}


@dataclass(frozen=True)
class Flag:
    code: str  # contact_url | contact_email | contact_phone | contact_handle | banned_goods
    field: str
    detail: str  # contact kind or banned category slug

    @property
    def message(self) -> str:
        if self.code == "banned_goods":
            return f"{self.field} mentions a prohibited item category ({self.detail})"
        return f"{self.field} contains {CONTACT_KINDS[self.code]}"


@lru_cache(maxsize=1)
def banned_terms() -> dict[str, tuple[tuple[str, ...], ...]]:
    """category -> tuple of normalized token tuples (both languages)."""
    with resources.files("ff_freight.data").joinpath("prohibited_goods.json").open(encoding="utf-8") as f:
        data = json.load(f)
    out: dict[str, tuple[tuple[str, ...], ...]] = {}
    for cat, langs in data["categories"].items():
        terms = {tuple(normalize(w).split()) for lang in langs.values() for w in lang if normalize(w)}
        out[cat] = tuple(sorted(terms))
    return out


_AR_PREFIXES = ("", "ال", "وال", "بال", "لل", "و", "ب", "ل")


def _contains(tokens: list[str], phrase: tuple[str, ...]) -> bool:
    n = len(phrase)
    for i in range(len(tokens) - n + 1):
        window = tokens[i : i + n]
        if all(_tok_eq(t, p) for t, p in zip(window, phrase, strict=True)):
            return True
    return False


def _tok_eq(tok: str, term: str) -> bool:
    if tok == term:
        return True
    if "a" <= term[0] <= "z" or term[0].isdigit():  # latin: allow a plain plural
        return tok in (term + "s", term + "es")
    return any(tok == p + term for p in _AR_PREFIXES)


def banned_categories(text: str) -> list[str]:
    toks = normalize(text).split()
    return [cat for cat, terms in banned_terms().items() if any(_contains(toks, t) for t in terms)]


def contact_kinds(text: str) -> list[str]:
    t = unicodedata.normalize("NFKC", text).translate(_AR_DIGITS)
    kinds = []
    if _URL.search(t):
        kinds.append("contact_url")
    if _EMAIL.search(t):
        kinds.append("contact_email")
    if any(sum(c.isdigit() for c in m.group()) >= _MIN_PHONE_DIGITS for m in _PHONE.finditer(t)):
        kinds.append("contact_phone")
    if _HANDLE.search(t):
        kinds.append("contact_handle")
    return kinds


def screen_fields(fields: dict[str, str | None]) -> list[Flag]:
    flags: list[Flag] = []
    for name, value in fields.items():
        if not value:
            continue
        flags += [Flag(k, name, k) for k in contact_kinds(value)]
        flags += [Flag("banned_goods", name, c) for c in banned_categories(value)]
    return flags


def reason_text(flags: list[Flag]) -> str:
    """Owner-facing, <= 400 chars, deduplicated; never echoes matched content."""
    seen: list[str] = []
    for f in flags:
        m = f.message
        if m not in seen:
            seen.append(m)
    base = "Automatic screening: " + "; ".join(seen[:4])
    if any(f.code != "banned_goods" for f in flags):
        base += ". Remove contact details and links; use in-app messaging"
    return base[:400]


def redact(text: str) -> str:
    """Mask emails, links and phone numbers in free text (report details are stored/shown to admins)."""
    t = unicodedata.normalize("NFKC", text).translate(_AR_DIGITS)
    t = _EMAIL.sub("[redacted]", t)
    t = _URL.sub("[redacted]", t)
    return _PHONE.sub(lambda m: "[redacted]" if sum(c.isdigit() for c in m.group()) >= 7 else m.group(), t)
