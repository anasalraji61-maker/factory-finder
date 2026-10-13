"""Small closed-class lexicons (folded Arabic incl. Iraqi dialect + English)."""

from __future__ import annotations

import re
from functools import cache

from ff_assistant.data import load_json
from ff_assistant.domain.matching import PhraseIndex, word_set

TO_MARKERS = word_set(
    ["الى", "لحد", "نحو", "to", "into", "towards", "toward", "يوصل", "توصل", "وصل", "يوصلون", "يوصلني", "deliver", "delivered", "delivery", "توصيل", "destination"]
)
FROM_MARKERS = word_set(["من", "from", "ex", "صنع", "made", "origin"])
IN_MARKERS = word_set(["في", "in", "at"])

TRACK_WORDS = word_set(["تتبع", "تعقب", "track", "tracking", "trace", "وين", "اين", "where"])
TRUST_WORDS = word_set(
    ["موثوق", "موثوقه", "ثقه", "trust", "trusted", "trustworthy", "reliable", "legit", "legitimate", "مصداقيه", "سمعه", "نصاب", "scam", "fraud", "امين"]
)
SHIP_WORDS = word_set(["شحن", "شحنه", "freight", "shipping", "landed", "جمارك"])
COST_WORDS = word_set(["شكد", "كم", "كلفه", "تكلفه", "تكاليف", "اجور", "اجره", "cost", "costs", "landed", "price"])
HELP_WORDS = word_set(
    ["مساعده", "ساعدني", "help", "شنو", "شكو", "مرحبا", "هلا", "السلام", "اهلا", "hi", "hello", "hey", "تكدر", "تقدر"]
)

USED_WORDS = word_set(["مستعمل", "مستعمله", "مستخدم", "مستخدمه", "used", "secondhand", "سكند"])
NEW_WORDS = word_set(["جديد", "جديده", "new"])
REFURB_WORDS = word_set(["مجدد", "مجدده", "refurbished", "reconditioned"])

MAX_WORDS = word_set(["اقل", "تحت", "under", "below", "less", "max", "maximum", "upto", "لحد", "اقصي"])
MIN_WORDS = word_set(["اكثر", "اعلي", "فوق", "above", "over", "more", "min", "minimum"])
BUDGET_CUES = word_set(["بسعر", "سعر", "ميزانيه", "budget", "price", "بحدود", "حدود", "around"])

CURRENCIES: dict[str, str] = {
    **dict.fromkeys(["دولار", "دولارات", "$", "usd", "dollar", "dollars", "دولاره"], "USD"),
    **dict.fromkeys(["دينار", "دنانير", "iqd", "دينارا"], "IQD"),
    **dict.fromkeys(["يورو", "€", "eur", "euro", "euros"], "EUR"),
    **dict.fromkeys(["يوان", "rmb", "cny", "yuan", "¥"], "CNY"),
}

# unit -> (canonical unit, kg per unit or None)
UNITS: dict[str, tuple[str, int | None]] = {
    **dict.fromkeys(["طن", "اطنان", "طنين", "ton", "tons", "tonne", "tonnes", "mt"], ("ton", 1000)),
    **dict.fromkeys(["كيلو", "كغم", "كلغ", "كجم", "kg", "kgs", "كيلوغرام", "كيلوجرام"], ("kg", 1)),
    **dict.fromkeys(
        ["قطعه", "قطع", "حبه", "حبات", "pcs", "pc", "piece", "pieces", "unit", "units", "وحده", "وحدات"], ("piece", None)
    ),
    **dict.fromkeys(["حاويه", "حاويات", "container", "containers"], ("container", None)),
    **dict.fromkeys(["متر", "امتار", "meter", "meters", "metre"], ("meter", None)),
    **dict.fromkeys(["لتر", "لترات", "liter", "litre", "liters", "litres"], ("liter", None)),
}

STOPWORDS = word_set(
    ["اريد", "ابي", "ابغي", "ابغى", "احتاج", "اطلب", "ارد", "اشتري", "اشتر", "اكو", "شكد", "منو", "عنده", "عندهم", "يوصل", "توصل", "وصل", "الى", "من", "في", "ب", "ل", "ك", "و", "مع", "عن", "او", "هل", "شنو", "شلون", "وين", "كم", "اني", "انا", "لو", "ممكن", "رجاء", "رجاءا", "بس", "هذا", "هذه", "ذلك", "سعر", "بسعر", "اقل", "اكثر", "من", "خط", "انتاج", "i", "need", "want", "a", "an", "the", "to", "from", "in", "of", "for", "with", "and", "or", "me", "my", "please", "delivered", "deliver", "delivery", "find", "looking", "look", "get", "buy", "is", "are", "can", "you", "do", "how", "much", "what", "price", "under", "over", "below", "above", "than", "at", "on", "by", "some", "any"]
)

KIND_PHRASES: PhraseIndex[str] = PhraseIndex(
    [
        *((p, "production_line") for p in (
            "خط انتاج", "خط إنتاج", "خطوط انتاج", "خطوط إنتاج", "production line",
            "assembly line", "production lines", "معمل كامل", "مصنع كامل", "turnkey plant",
        )),
        *((p, "raw_material") for p in (
            "مواد اولية", "مواد أولية", "مادة اولية", "مادة أولية", "مواد خام", "مادة خام",
            "raw material", "raw materials",
        )),
    ]
)

REF_RES = {
    "container": re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{4}\s?\d{7}(?![A-Za-z0-9])"),
    "vessel_imo": re.compile(r"(?i)\bIMO\s?[:#]?\s?\d{7}\b"),
    "awb": re.compile(r"(?<!\d)\d{3}[- ]\d{8}(?!\d)"),
}
SUPPLIER_RE = re.compile(r"(?i)\bsup_[a-z0-9]+(?:_[a-z0-9]+)*\b")


@cache
def glossary_index() -> PhraseIndex[dict]:
    index: PhraseIndex[dict] = PhraseIndex()
    for entry in load_json("glossary.json")["entries"]:
        for phrase in (*entry["ar"], entry["en"], *entry.get("en_aliases", [])):
            index.add(phrase, entry)
    return index
