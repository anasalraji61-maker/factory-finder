"""Arabic/English text normalization, light stemming and bilingual synonyms."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_ARABIC_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ة": "ه",
        **{chr(0x0660 + i): str(i) for i in range(10)},
        **{chr(0x06F0 + i): str(i) for i in range(10)},
    }
)
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)

STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "for",
    "and",
    "or",
    "in",
    "with",
    "to",
    "from",
    "by",
    "on",
    "new",
    "جديد",
    "جديده",
    "و",
    "في",
    "من",
    "مع",
    "الى",
    "على",
    "عن",
    "ل",
    "لل",
    "او",
}


def normalize(text: str) -> str:
    """Lowercase, strip diacritics/tatweel, unify alef/yaa/taa-marbuta, ASCII digits."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = _DIACRITICS.sub("", text).translate(_ARABIC_MAP)
    return _NON_WORD.sub(" ", text).strip()


def stem(token: str) -> str:
    """Strip Arabic definite article (repeatedly) and English plural 's'."""
    while token.startswith("ال") and len(token) > 4:
        token = token[2:]
    if token.isascii() and len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    return token


def tokens(text: str) -> list[str]:
    return [stem(t) for t in normalize(text).split() if t]


# Equivalence groups; first item is the canonical English keyword for remote APIs.
_SYNONYM_GROUPS: list[list[str]] = [
    ["production line", "خط انتاج", "خطوط انتاج", "خط تصنيع", "مصنع جاهز", "assembly line"],
    [
        "machine",
        "machinery",
        "equipment",
        "مكينه",
        "ماكنه",
        "ماكينه",
        "مكنه",
        "ماكينات",
        "ماكنات",
        "معدات",
        "آلة",
        "الة",
    ],
    [
        "pastry",
        "bakery",
        "bread",
        "croissant",
        "معجنات",
        "مخبوزات",
        "مخبز",
        "افران",
        "خبز",
        "كرواسون",
    ],
    ["biscuit", "cookie", "cracker", "بسكويت", "كوكيز", "بسكويت"],
    ["bottle", "bottling", "قنينه", "قناني", "زجاجه", "عبوه", "تعبئه"],
    ["water", "ماء", "مياه", "ميه"],
    ["juice", "عصير", "عصائر"],
    ["injection molding", "injection moulding", "حقن بلاستيك", "ماكنه حقن"],
    ["extrusion", "extruder", "بثق", "اكسترودر"],
    ["laser cutting", "laser cutter", "قص ليزر", "ليزر"],
    ["concrete block", "block making", "بلوك", "طابوق", "بلوك خرساني"],
    ["flour mill", "mill", "مطحنه", "طحين", "طحن"],
    ["oil press", "edible oil", "عصر زيت", "معصره", "زيوت"],
    ["tissue paper", "toilet paper", "ورق التواليت", "ورق تواليت", "محارم", "ورق صحي"],
    ["carton", "corrugated", "cardboard", "كرتون", "كارتون", "مموج"],
    ["used", "second hand", "secondhand", "مستعمل", "مستعمله", "مستخدم"],
    ["granule", "granules", "resin", "chips", "حبيبات", "حبيبه", "بيليت", "راتنج"],
    ["polypropylene", "pp", "بولي بروبيلين", "بولي بروبلين", "بولبروبلين"],
    ["polyethylene", "pe", "hdpe", "ldpe", "بولي ايثيلين", "بولي اثيلين", "بولي ايثلين"],
    ["pet", "بولي ايثيلين تيريفثالات"],
    ["steel", "حديد", "صلب", "فولاذ", "ستيل"],
    ["rebar", "reinforcing bar", "حديد تسليح", "سيخ"],
    ["aluminium", "aluminum", "المنيوم", "المونيوم", "المنيم"],
    ["copper", "نحاس"],
    ["yarn", "thread", "خيوط", "خيط", "غزل"],
    ["cotton", "قطن", "قطني"],
    ["polyester", "بوليستر"],
    ["fabric", "textile", "cloth", "قماش", "اقمشه", "نسيج", "منسوجات"],
    ["paper", "ورق"],
    ["wood", "plywood", "timber", "panel", "خشب", "اخشاب", "الواح خشب", "خشب رقائقي"],
    ["chair", "كرسي", "كراسي", "مقعد", "مقاعد"],
    ["table", "طاوله", "طاولات", "ميز"],
    ["furniture", "اثاث", "فرنيتشر"],
    ["office", "مكتب", "مكتبي"],
    ["led", "ليد", "لد"],
    ["light", "lighting", "lamp", "اضاءه", "انارة", "انارت", "كشاف", "مصباح", "مصابيح", "لمبه"],
    [
        "solar panel",
        "photovoltaic",
        "pv module",
        "الواح شمسيه",
        "لوح شمسي",
        "الواح شمسية",
        "خلايا شمسيه",
        "الواح طاقه شمسيه",
    ],
    ["solar", "شمسي", "شمسيه", "طاقه شمسيه"],
    ["inverter", "محول", "انفرتر", "انفيرتر", "عاكس"],
    ["kitchenware", "cookware", "kitchen", "مطبخ", "اواني", "اواني طبخ", "ادوات مطبخ", "قدور"],
    ["tire", "tyre", "اطار", "اطارات", "تاير", "تايرات", "كفرات", "كفر"],
    ["truck", "شاحنه", "شاحنات", "لوري", "حمل"],
    ["abaya", "عباءه", "عباءة", "عبايه", "عبايات", "عباية"],
    ["modest", "hijab", "محتشم", "محتشمه", "حجاب", "ازياء محتشمه"],
    ["dress", "فستان", "فساتين", "ثوب"],
    ["tool", "tools", "عده", "عدد", "ادوات", "اداة", "أدوات"],
    ["drill", "مثقاب", "دريل", "دريلات"],
    ["auto part", "car part", "spare part", "قطع غيار", "قطع سيارات", "غيار سيارات"],
    ["brake", "فرامل", "فحمات", "بريك"],
    ["pump", "مضخه", "مضخات", "مضخة", "طلمبه", "بمب", "مضخه ماء"],
    ["submersible", "غاطس", "غاطسه"],
    ["air conditioner", "air conditioning", "ac", "split", "مكيف", "مكيفات", "سبلت", "تكييف"],
    ["cnc", "machining center", "سي ان سي", "مركز تشغيل", "خراطه"],
    ["printing", "offset", "طباعه", "اوفست"],
]


@dataclass(frozen=True)
class QueryTerm:
    original: str
    alternatives: tuple[tuple[str, ...], ...]  # each alternative is a stemmed token sequence


def _phrase_tokens(p: str) -> tuple[str, ...]:
    return tuple(tokens(p))


@lru_cache(maxsize=1)
def _phrase_index() -> tuple[dict[tuple[str, ...], int], list[list[tuple[str, ...]]], int]:
    idx: dict[tuple[str, ...], int] = {}
    groups: list[list[tuple[str, ...]]] = []
    longest = 1
    for gi, g in enumerate(_SYNONYM_GROUPS):
        alts: list[tuple[str, ...]] = []
        for p in g:
            t = _phrase_tokens(p)
            if t and t not in alts:
                alts.append(t)
                idx.setdefault(t, gi)
                longest = max(longest, len(t))
        groups.append(alts)
    return idx, groups, longest


def parse_query(q: str) -> list[QueryTerm]:
    """Greedy longest-phrase synonym expansion; unknown tokens stay literal."""
    idx, groups, longest = _phrase_index()
    toks = [t for t in tokens(q) if t not in STOPWORDS]
    out: list[QueryTerm] = []
    i = 0
    while i < len(toks):
        for n in range(min(longest, len(toks) - i), 0, -1):
            span = tuple(toks[i : i + n])
            gi = idx.get(span)
            if gi is None and n == 1 and span[0].startswith("و") and len(span[0]) > 3:
                span = (stem(span[0][1:]),)  # conjunction prefix: وكراسي -> كراسي
                gi = idx.get(span)
            if gi is not None:
                out.append(QueryTerm(" ".join(span), tuple(groups[gi])))
                i += n
                break
        else:
            out.append(QueryTerm(toks[i], ((toks[i],),)))
            i += 1
    return out


def english_keywords(q: str) -> list[str]:
    """Canonical English keyword per query term (for remote APIs)."""
    _, groups, _ = _phrase_index()
    kws: list[str] = []
    for term in parse_query(q):
        first = term.alternatives[0]
        kws.append(" ".join(first) if first and first[0].isascii() else term.original)
    return kws


def contains_phrase(doc_tokens: list[str], phrase: tuple[str, ...]) -> bool:
    n = len(phrase)
    if n == 0:
        return False
    if n == 1:
        return phrase[0] in doc_tokens
    return any(tuple(doc_tokens[i : i + n]) == phrase for i in range(len(doc_tokens) - n + 1))
