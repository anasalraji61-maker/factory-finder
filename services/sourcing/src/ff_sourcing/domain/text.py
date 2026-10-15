"""Arabic/English text normalization, light stemming and bilingual synonyms."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06dc\u06df-\u06e8\u06ea-\u06ed\u0640]")
_ARABIC_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ة": "ه",
        "ؤ": "و",
        "ئ": "ي",
        "گ": "ك",  # Iraqi/Persian letters -> nearest Arabic
        "چ": "ج",
        "پ": "ب",
        "ڤ": "ف",
        "ک": "ك",
        "ی": "ي",
        "ہ": "ه",
        **{chr(0x0660 + i): str(i) for i in range(10)},
        **{chr(0x06F0 + i): str(i) for i in range(10)},
    }
)
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)
_CJK = re.compile(r"([\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff])")

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
    """Lowercase, strip diacritics/tatweel/accents, unify alef/yaa/taa-marbuta, ASCII digits."""
    text = unicodedata.normalize("NFKD", text or "").lower()
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = _DIACRITICS.sub("", text).translate(_ARABIC_MAP)
    text = _CJK.sub(r" \1 ", text)  # each Chinese character is its own token
    return _NON_WORD.sub(" ", text).strip()


_AR_PREFIXES = ("وال", "بال", "فال", "كال", "لل", "ال")


def stem(token: str) -> str:
    """Strip Arabic definite article/clitic prefixes and English plural endings."""
    while len(token) > 4:
        for p in _AR_PREFIXES:
            if token.startswith(p) and len(token) - len(p) >= 3:
                token = token[len(p) :]
                break
        else:
            break
    if not token.isascii() and len(token) >= 5 and token.endswith("ات"):
        token = token[:-2] + "ه"  # sound feminine plural == singular after ة->ه (سيارات / سيارة)
    if token.isascii() and len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        if token.endswith("ies") and len(token) > 4:
            return token[:-3] + "y"
        if token.endswith(("xes", "ches", "shes", "sses")) and len(token) > 4:
            return token[:-2]
        return token[:-1]
    return token


# Unit vocabulary: every spelling (post-normalize/stem) -> one canonical token, so "250 كغم" == "250kg" == "250 kilogram".
_UNIT_SPELLINGS: dict[str, tuple[str, ...]] = {
    "kg": ("kg", "kgs", "kilo", "kilogram", "kilogramme", "كغ", "كغم", "كجم", "كلغ", "كيلو", "كيلوغرام", "كيلوجرام"),
    "ton": ("ton", "tonne", "tonnes", "mt", "طن", "اطنان", "أطنان", "吨"),
    "meter": ("m", "meter", "metre", "متر", "امتار", "米"),
    "liter": ("l", "liter", "litre", "لتر", "لتره", "لترات", "升"),
    "pc": ("pc", "pcs", "piece", "pce", "قطعه", "قطع", "件", "个"),
    "set": ("set", "طقم", "اطقم", "套"),
    "pair": ("pair", "prs", "زوج", "ازواج", "双", "对"),
    "dozen": ("dozen", "doz", "دزينه", "打"),
    "m2": ("m2", "sqm"),
    "m3": ("m3", "cbm"),
}
_UNIT = {stem(normalize(sp)): canon for canon, sps in _UNIT_SPELLINGS.items() for sp in sps}
_UNIT.update({normalize(sp): canon for canon, sps in _UNIT_SPELLINGS.items() for sp in sps})
_NUM_UNIT = re.compile(r"^(\d+)([^\W\d_]+)$", re.UNICODE)  # 250kg / 250كغم (digits then letters, nothing else)


@lru_cache(maxsize=16384)
def tokens(text: str) -> tuple[str, ...]:
    out: list[str] = []
    for raw in normalize(text).split():
        m = _NUM_UNIT.match(raw)
        # 250kg/h -> 250 kg h; bare "l" is never split off (steel grades 304L / 316L)
        if m and m.group(2) != "l" and (_UNIT.get(m.group(2)) or _UNIT.get(stem(m.group(2)))):
            out.append(m.group(1))
            raw = m.group(2)
        t = stem(raw)
        out.append(_UNIT.get(t) or _UNIT.get(raw) or t)
    return tuple(out)


# Equivalence groups; first item is the canonical English keyword for remote APIs.
_SYNONYM_GROUPS: list[list[str]] = [
    ["production line", "خط انتاج", "خطوط انتاج", "خط تصنيع", "مصنع جاهز", "assembly line", "خط انتاج", "生产线", "流水线"],
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
        "مكائن",
        "ماكينه",
        "مكاين",
        "机器",
        "机械",
        "设备",
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
    ["biscuit", "cookie", "cracker", "بسكويت", "كوكيز", "بسكوت", "饼干"],
    ["bottle", "bottling", "قنينه", "قناني", "قنينات", "عبوه", "عبوات", "تعبئه", "瓶", "瓶子"],
    ["water", "ماء", "مياه", "ميه", "ماي", "水"],
    ["juice", "عصير", "عصائر"],
    ["injection molding", "injection moulding", "حقن بلاستيك", "注塑机", "注塑"],
    ["blow", "blowing", "blow molding", "blow moulding", "نفخ", "吹塑"],
    ["extrusion", "extruder", "بثق", "اكسترودر"],
    ["laser cutting", "laser cutter", "قص ليزر", "ليزر", "激光切割", "激光"],
    ["concrete block", "block making", "بلوك", "بلوك خرساني"],
    ["flour mill", "mill", "مطحنه", "طحين", "طحن"],
    ["oil press", "edible oil", "عصر زيت", "معصره", "زيوت"],
    ["tissue paper", "toilet paper", "ورق التواليت", "ورق تواليت", "محارم", "ورق صحي"],
    ["corrugated", "مموج"],
    ["carton", "cardboard", "box", "كرتون", "كارتون", "كراتين", "علب كرتون"],
    ["used", "second hand", "secondhand", "مستعمل", "مستعمله", "مستخدم", "مستخدمه", "二手"],
    ["granule", "granules", "resin", "chips", "حبيبات", "حبيبه", "بيليت", "راتنج"],
    ["polypropylene", "pp", "بولي بروبيلين", "بولي بروبلين", "بولبروبلين"],
    ["polyethylene", "pe", "hdpe", "ldpe", "بولي ايثيلين", "بولي اثيلين", "بولي ايثلين"],
    ["pet", "بولي ايثيلين تيريفثالات", "بيت", "بي اي تي", "بت"],
    ["stainless", "stainless steel", "ستانلس", "ستانلس ستيل", "استانلس", "ستنلس", "ستينلس", "ستيل ستانلس", "فولاذ مقاوم للصدا", "مقاوم للصدا", "不锈钢"],
    ["coil", "كويل", "لفه", "لفات", "卷"],
    ["roll", "jumbo roll", "رول", "رولات", "رولة", "جامبو"],
    ["sheet", "plate", "صفيحه", "صفائح", "شيت", "شيتات", "ورقه معدنيه"],
    ["denim", "jeans", "دنيم", "جينز", "جنز"],
    ["tempering", "tempered", "تقسيه", "مقسي", "مقسى", "مقسيه"],
    ["women", "woman", "ladies", "female", "نسائي", "نسائيه", "نساء", "حريمي", "للنساء"],
    ["refurbished", "renovated", "reconditioned", "مجدد", "مجدده", "معاد تاهيل"],
    ["steel", "حديد", "صلب", "فولاذ", "ستيل", "钢", "钢材"],
    ["rebar", "reinforcing bar", "حديد تسليح", "حديد بناء", "حديد انشائي", "سيخ"],
    ["aluminium", "aluminum", "المنيوم", "المونيوم", "المنيم", "المينيوم", "铝"],
    ["copper", "نحاس", "铜"],
    ["yarn", "thread", "خيوط", "خيط", "غزل"],
    ["cotton", "قطن", "قطني", "棉", "棉花"],
    ["polyester", "بوليستر"],
    ["fabric", "textile", "cloth", "قماش", "اقمشه", "نسيج", "منسوجات", "布", "面料", "纺织"],
    ["paper", "ورق", "اوراق", "纸"],
    ["plywood", "خشب رقائقي", "ابلكاش", "ابلاكاش", "بلايوود", "胶合板"],
    ["wood", "timber", "panel", "plywood", "خشب", "اخشاب", "الواح خشب", "خشب رقائقي", "木", "木材"],
    ["chair", "كرسي", "كراسي", "كرسيه", "كراسيه", "مقعد", "مقاعد", "椅子", "椅"],
    ["table", "طاوله", "طاولات", "طاولة", "ميز", "桌子", "桌"],
    ["furniture", "اثاث", "فرنيتشر", "家具"],
    ["office", "مكتب", "مكتبي", "办公"],
    ["led", "ليد", "لد", "发光二极管"],
    ["light", "lighting", "lamp", "اضاءه", "انارة", "انارت", "كشاف", "مصباح", "مصابيح", "لمبه", "لمبات", "灯", "灯具", "照明"],
    [
        "solar panel",
        "photovoltaic",
        "pv module",
        "الواح شمسيه",
        "لوح شمسي",
        "الواح شمسية",
        "خلايا شمسيه",
        "الواح طاقه شمسيه",
        "光伏板",
        "太阳能板",
        "光伏",
    ],
    ["solar", "شمسي", "شمسيه", "طاقه شمسيه", "太阳能"],
    ["inverter", "محول", "انفرتر", "انفيرتر", "عاكس"],
    ["kitchenware", "cookware", "kitchen", "مطبخ", "اواني", "اواني طبخ", "ادوات مطبخ", "قدور"],
    ["tire", "tyre", "اطار", "اطارات", "تاير", "تايرات", "كفرات", "كفر", "كفرات", "轮胎"],
    ["truck", "شاحنه", "شاحنات", "لوري", "حمل", "卡车", "货车"],
    ["abaya", "عباءه", "عباءة", "عبايه", "عبايات", "عباية"],
    ["modest", "hijab", "محتشم", "محتشمه", "حجاب", "ازياء محتشمه"],
    ["dress", "فستان", "فساتين", "ثوب"],
    ["tool", "tools", "عده", "عدد", "ادوات", "اداة", "أدوات"],
    ["drill", "مثقاب", "دريل", "دريلات"],
    ["auto part", "car part", "spare part", "قطع غيار", "قطع سيارات", "غيار سيارات"],
    ["brake", "فرامل", "فحمات", "بريك"],
    [
        "water pump",
        "مضخه ماء",
        "مضخه مياه",
        "مضخات مياه",
        "مضخات ماء",
        "طلمبه ماء",
        "طلمبه مياه",
        "طلمبه ماي",
        "مضخه ميه",
        "水泵",
    ],
    ["pump", "مضخه", "مضخات", "مضخة", "طلمبه", "طلمبات", "بمب", "泵"],
    ["submersible", "غاطس", "غاطسه"],
    ["air conditioner", "air conditioning", "ac", "split", "مكيف", "مكيفات", "سبلت", "تكييف", "空调"],
    ["lathe", "turning", "turning center", "turning machine", "مخرطه", "مخارط", "خراطه", "مركز خراطه", "车床"],
    ["cnc", "machining center", "سي ان سي", "مركز تشغيل", "数控", "加工中心"],
    ["printing", "offset", "طباعه", "اوفست", "印刷"],
    ["plastic", "plastics", "بلاستيك", "بلاستك", "بلاستيكي", "塑料"],
    ["generator", "genset", "مولد", "مولده", "مولدات", "مولد كهرباء", "مولده كهرباء", "مولد كهربائي", "جنريتر", "جنريتر", "发电机"],
    ["battery", "batteries", "بطاريه", "بطاريات", "باطريه", "بطارية", "电池"],
    ["tank", "خزان", "خزانات", "تانكي", "تنكي", "水箱"],
    ["tile", "tiles", "بلاط", "كاشي", "تايل", "تايلز", "瓷砖"],
    ["ceramic", "سيراميك", "陶瓷"],
    ["porcelain", "بورسلان", "بورسلين"],
    ["glass", "زجاج", "زجاجي", "زجاجيه", "قزاز", "玻璃"],
    ["sewing", "خياطه", "خياط", "sewing machine", "ماكينه خياطه", "缝纫", "缝纫机"],
    ["printer", "3d printer", "طابعه", "طابعات", "打印机"],
    ["cable", "wire", "cord", "كابل", "كيبل", "سلك", "اسلاك", "电缆"],
    ["film", "فيلم", "فلم", "نايلون", "薄膜"],
    ["leather", "جلد", "جلود", "جلديه", "皮革"],
    ["pipe", "tube", "انبوب", "انابيب", "ماسوره", "مواسير", "بايب", "管"],
    ["packaging", "packing", "wrapping", "تغليف", "تعبئه وتغليف", "تغليف", "包装"],
    ["label", "labeling", "labelling", "sticker", "ملصق", "ملصقات", "ستيكر", "标签"],
    ["brick", "bricks", "طوب", "اجر", "طابوق", "طابوق طيني", "砖"],
    ["fertilizer", "fertiliser", "سماد", "اسمده", "سمد", "肥料"],
    ["toy", "toys", "لعبه", "العاب", "دميه", "دمي", "玩具"],
    ["cctv", "security camera", "surveillance camera", "كاميرا مراقبه", "كاميرات مراقبه", "مراقبه", "监控"],
    ["camera", "cctv", "security camera", "كاميرا", "كاميرات", "摄像头"],
    ["charger", "charging", "شاحن", "شواحن", "充电器"],
    ["sprayer", "رشاش", "مرشه", "مرش", "喷雾器"],
    ["cigarette", "cigarettes", "سجائر", "سجاير", "جكاير", "جكاره", "سكائر", "香烟"],
    ["flour", "wheat", "دقيق", "面粉"],
    ["air cooler", "cooler", "مبرد", "مبرد هواء", "كولر", "冷风机"],
    ["food", "غذاء", "اغذيه", "طعام", "食品"],
]


@dataclass(frozen=True)
class QueryTerm:
    original: str
    alternatives: tuple[tuple[str, ...], ...]  # each alternative is a stemmed token sequence
    fuzzy: str | None = None  # literal (unknown-word) token that may match doc tokens with typos


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


@lru_cache(maxsize=1)
def _single_vocab() -> tuple[tuple[str, int], ...]:
    """Single-token synonym keys eligible as typo-correction targets (len >= 4, alphabetic)."""
    idx, _, _ = _phrase_index()
    return tuple((t[0], gi) for t, gi in idx.items() if len(t) == 1 and _fuzzable(t[0]))


# ---- typo tolerance --------------------------------------------------------
def _fuzzable(tok: str) -> bool:
    return len(tok) >= 4 and tok.isalpha()


def _osa(a: str, b: str, limit: int) -> int:
    """Optimal-string-alignment distance (insert/delete/substitute/transpose); > limit -> limit+1."""
    la, lb = len(a), len(b)
    if abs(la - lb) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        best = cur[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
            best = min(best, v)
        if best > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[lb]


def typo_distance(q: str, d: str) -> int | None:
    """Edit distance if ``d`` is an acceptable typo of ``q``, else None.

    Guards against matching unrelated words: both tokens >= 4 alphabetic chars, same first letter,
    distance 1 (2 only when both are >= 8 chars), and for 4-letter words no same-length
    substitution (tile/tire, pipe/pine) - only transposition or a missing/extra letter.
    """
    if q == d:
        return 0
    if not (_fuzzable(q) and _fuzzable(d)) or q[0] != d[0]:
        return None
    short = min(len(q), len(d))
    limit = 2 if short >= 8 else 1
    if abs(len(q) - len(d)) > limit:
        return None
    dist = _osa(q, d, limit)
    if dist > limit:
        return None
    if short == 4 and len(q) == len(d) and dist == 1 and sorted(q) != sorted(d):
        return None
    return dist


def _correct(token: str) -> int | None:
    """Group index of the unique closest synonym keyword within typo distance, else None."""
    if not _fuzzable(token):
        return None
    best: dict[int, int] = {}
    for key, gi in _single_vocab():
        d = typo_distance(token, key)
        if d is not None and d < best.get(gi, 99):
            best[gi] = d
    if not best:
        return None
    m = min(best.values())
    winners = [gi for gi, d in best.items() if d == m]
    return winners[0] if len(winners) == 1 else None


def parse_query(q: str) -> list[QueryTerm]:
    """Greedy longest-phrase synonym expansion; typo-corrected where unambiguous."""
    idx, groups, longest = _phrase_index()
    toks = [t for t in tokens(q) if t not in STOPWORDS]
    out: list[QueryTerm] = []
    seen_groups: set[int] = set()  # two words of one synonym group (مكيف سبلت) are one concept
    i = 0
    while i < len(toks):
        for n in range(min(longest, len(toks) - i), 0, -1):
            span = tuple(toks[i : i + n])
            gi = idx.get(span)
            if gi is None and n == 1 and span[0].startswith("و") and len(span[0]) > 3:
                span = (stem(span[0][1:]),)  # conjunction prefix: وكراسي -> كراسي
                gi = idx.get(span)
            if gi is not None:
                if gi not in seen_groups:
                    seen_groups.add(gi)
                    out.append(QueryTerm(" ".join(span), tuple(groups[gi])))
                i += n
                break
        else:
            tok = toks[i]
            gi = _correct(tok)
            if gi is not None:  # typo of a known term: expand its group (keep the literal too)
                if gi not in seen_groups:
                    seen_groups.add(gi)
                    out.append(QueryTerm(tok, (*groups[gi], (tok,))))
            else:
                out.append(QueryTerm(tok, ((tok,),), fuzzy=tok if _fuzzable(tok) else None))
            i += 1
    return out


def query_phrase(q: str) -> tuple[str, ...]:
    """Stemmed query tokens (stopwords dropped) used for the exact-phrase title boost."""
    return tuple(t for t in tokens(q) if t not in STOPWORDS)


def english_keywords(q: str) -> list[str]:
    """Canonical English keyword per query term (for remote APIs)."""
    _, groups, _ = _phrase_index()
    kws: list[str] = []
    for term in parse_query(q):
        first = term.alternatives[0]
        kws.append(" ".join(first) if first and first[0].isascii() else term.original)
    return kws


def contains_phrase(doc_tokens: Sequence[str], phrase: tuple[str, ...]) -> bool:
    n = len(phrase)
    if n == 0:
        return False
    if n == 1:
        return phrase[0] in doc_tokens
    return any(tuple(doc_tokens[i : i + n]) == phrase for i in range(len(doc_tokens) - n + 1))


def fuzzy_in(doc_tokens: Sequence[str], token: str) -> bool:
    """True when some doc token is an acceptable typo of ``token`` (never for exact hits)."""
    variants = (token, token + "s")  # stem() may have eaten a typo'd word's final "s"
    return any(typo_distance(v, d) is not None for d in doc_tokens for v in variants)
