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
SHIP_WORDS = word_set(["شحن", "شحنه", "freight", "shipping", "ship", "landed", "جمارك"])
COST_WORDS = word_set(["شكد", "كم", "much", "كلفه", "تكلفه", "تكاليف", "اجور", "اجره", "cost", "costs", "landed", "price"])
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
INCOTERM_RE = re.compile(r"(?i)(?<![A-Za-z])(EXW|FCA|FOB|CFR|CIF|DAP|DDP)(?![A-Za-z])|(?<!\S)(فوب)(?!\S)")
DOOR_RE = re.compile(r"(?i)لحد\s+(?:ال)?باب|door[- ]to[- ]door|doorstep|landed")
# clearly non-sourcing chatter / compliance questions (only honoured when no product term was recognised)
OFFTOPIC_RE = re.compile(
    r"(?i)\b(?:poem|poetry|joke|jokes|football|soccer|match|weather|recipe|horoscope|lyrics|song|movie|news|stock|bitcoin|crypto|homework)\b|"
    r"قصيد[ةه]|شعر|نكت[ةه]|احجيلي|طقس|مباراة|كرة|وصف[ةه]\s+(?:اكل|طبخ)|برج|اغنيه|اغنية|فيلم|اخبار|أخبار"
)
COMPLIANCE_RE = re.compile(
    r"(?i)\bdocuments?\b|\bdocumentation\b|certificate of origin|\bimport (?:requirements?|permit|licen[cs]e)|\bcompliance\b|"
    r"وثائق|مستندات|شهاد[ةه]\s+منشأ|شهاد[ةه]\s+المنشأ|معاينة|اجازة\s+استيراد|إجازة\s+استيراد|متطلبات\s+الاستيراد"
)
SUPPLIER_RE = re.compile(r"(?i)\bsup_[a-z0-9]+(?:_[a-z0-9]+)*\b")
LISTING_RE = re.compile(r"(?i)\blst_[a-z0-9]+(?:_[a-z0-9]+)*\b")
DEAL_RE = re.compile(r"(?i)\bdeal_[a-z0-9]+(?:_[a-z0-9]+)*\b")
# tool intents (raw, unfolded text; Arabic variants spelled out)
COMPARE_RE = re.compile(r"(?i)\bcompare\b|\bcomparison\b|\bvs\.?(?=\s|$)|\bversus\b|قارن|مقارن|مقابل|الفرق بين|ايهما|أيهما|اي منهم")
HS_RE = re.compile(
    r"(?i)\bhs\b|\bhs[- ]?codes?\b|harmoni[sz]ed|\btariff\b|customs code|"
    r"(?:رمز|كود|رقم|بند)\s+(?:ال)?(?:جمرك[يى]?|جمارك|hs)|تعرف[ةه]\s+(?:ال)?(?:جمرك[يى]?|جمارك)|رمز\s+الـ?\s*hs"
)
HS_CODE_RE = re.compile(r"(?<![\d.])\d{4}(?:[. ]?\d{2}){1,2}(?![\d])|(?<![\d.])\d{6,10}(?![\d])")
DEAL_PHRASE_RE = re.compile(
    r"(?i)payment status|deal status|status of (?:my )?(?:deal|payment)|my (?:deal|payment)|did i pay|"
    r"(?:is|was) (?:it|my \w+) paid|حالة (?:ال)?(?:دفع|صفق)|صفقتي|دفعتي|دفعتك|هل (?:تم|انا دفعت)|صفقه|الصفقة"
)
STATUS_WORDS = word_set(
    ["حاله", "status", "وين", "اين", "where", "eta", "موعد", "وصلت", "وصول", "متى", "when", "arrive", "arrived", "arrival", "شنو"]
)


@cache
def glossary_index() -> PhraseIndex[dict]:
    index: PhraseIndex[dict] = PhraseIndex()
    for entry in load_json("glossary.json")["entries"]:
        for phrase in (*entry["ar"], entry["en"], *entry.get("en_aliases", [])):
            index.add(phrase, entry)
    return index

HS_NOISE = word_set(["hs", "code", "codes", "tariff", "harmonized", "customs", "رمز", "كود", "رقم", "بند", "جمركي", "الجمركي", "جمرك", "تعرفه", "التعرفه", "لل", "ما", "ماهو", "ماهي", "what", "which", "whats", "find", "lookup", "search"])
