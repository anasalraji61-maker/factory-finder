"""Price / unit / condition / year-of-manufacture normalization for free-text supplier listings.

Pure, deterministic, no I/O. Money is ``Decimal`` only (CLAUDE.md rule 8). Ambiguity is FLAGGED, never guessed:
``ParsedPrice.flags`` entries prefixed ``ambiguous_`` mean a value was withheld (``None``) or a literal reading
was returned together with the candidates; other flags are informational.

  * parse_price_text  - '$10 (100-499 pcs); $8 (500+ pcs)', '¥12/件', '50 دولار للطن', 'from US$3.5 / kg' ...
  * detect_currency_ex - symbol/word/ISO -> (code, candidates, flags); '¥' is CNY-or-JPY, resolved only by evidence
  * normalize_unit    - 件 / 套 / 吨 / قطعة / طن / per set / m² ... -> canonical unit
  * convert_unit_price - per-ton <-> per-kg etc. Only within one physical dimension (set/carton/pair never converted)
  * parse_condition / parse_year - new|used|refurbished and year of manufacture from title/description text
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .text import _ARABIC_MAP, _DIACRITICS

# --------------------------------------------------------------------------------------- folding
_AR_SEPS = str.maketrans({"٫": ".", "٬": ",", "،": ",", "؛": ";"})


def _fold(text: object) -> str:
    """NFKC (full-width, ², ㎡), lowercase, Arabic letter/digit unification; punctuation is kept."""
    s = unicodedata.normalize("NFKC", str(text or "")).lower()
    s = _DIACRITICS.sub("", s).translate(_ARABIC_MAP).translate(_AR_SEPS)
    return s


# --------------------------------------------------------------------------------------- units
# canonical -> (dimension, factor to the dimension's base unit or None when not convertible)
_UNIT_INFO: dict[str, tuple[str, Decimal | None]] = {
    "pc": ("count", Decimal(1)),
    "dozen": ("count", Decimal(12)),
    "pair": ("pair", None),
    "set": ("set", None),
    "carton": ("pack", None),
    "bag": ("pack", None),
    "roll": ("pack", None),
    "box": ("pack", None),
    "pallet": ("pack", None),
    "kg": ("mass", Decimal(1)),
    "g": ("mass", Decimal("0.001")),
    "ton": ("mass", Decimal(1000)),  # metric tonne (Alibaba 'Ton' / 'MT' / 吨 / طن)
    "short_ton": ("mass", Decimal("907.18474")),
    "long_ton": ("mass", Decimal("1016.0469088")),
    "lb": ("mass", Decimal("0.45359237")),
    "m": ("length", Decimal(1)),
    "cm": ("length", Decimal("0.01")),
    "mm": ("length", Decimal("0.001")),
    "km": ("length", Decimal(1000)),
    "ft": ("length", Decimal("0.3048")),
    "m2": ("area", Decimal(1)),
    "ft2": ("area", Decimal("0.09290304")),
    "m3": ("volume", Decimal(1000)),  # base = liter
    "liter": ("volume", Decimal(1)),
    "ml": ("volume", Decimal("0.001")),
    "gallon": ("volume", Decimal("3.785411784")),  # US gallon
}

_UNIT_SPELLINGS: dict[str, tuple[str, ...]] = {
    "pc": ("pc", "pcs", "piece", "pieces", "unit", "units", "item", "items", "each", "ea", "قطعه", "قطع", "وحده", "حبه", "件", "个", "個", "台", "只", "支", "条", "张"),
    "dozen": ("dozen", "dozens", "doz", "dz", "دزينه", "دستة", "دسته", "打"),
    "pair": ("pair", "pairs", "prs", "زوج", "ازواج", "جوز", "对", "双", "對", "雙"),
    "set": ("set", "sets", "طقم", "اطقم", "مجموعه", "套", "組"),
    "carton": ("carton", "cartons", "ctn", "ctns", "كرتون", "كرتونه", "كراتين", "箱"),
    "bag": ("bag", "bags", "كيس", "اكياس", "袋"),
    "roll": ("roll", "rolls", "رول", "رولات", "卷"),
    "box": ("box", "boxes", "علبه", "علب", "صندوق", "盒"),
    "pallet": ("pallet", "pallets", "palette", "طبليه", "باليت", "托"),
    "kg": ("kg", "kgs", "kilo", "kilos", "kilogram", "kilograms", "kilogramme", "كغ", "كغم", "كجم", "كلغ", "كيلو", "كيلوغرام", "كيلوجرام", "公斤", "千克"),
    "g": ("gram", "grams", "gr", "غرام", "جرام", "克"),
    "ton": ("ton", "tons", "tonne", "tonnes", "mt", "metric ton", "metric tons", "metric tonne", "طن", "اطنان", "طنا", "吨", "噸"),
    "short_ton": ("short ton", "short tons", "us ton", "net ton"),
    "long_ton": ("long ton", "long tons", "uk ton", "imperial ton"),
    "lb": ("lb", "lbs", "pound", "pounds", "رطل", "ارطال", "磅"),
    "m": ("m", "meter", "meters", "metre", "metres", "mtr", "متر", "امتار", "米"),
    "cm": ("cm", "centimeter", "centimeters", "centimetre", "سم", "سنتيمتر", "厘米"),
    "mm": ("mm", "millimeter", "millimeters", "ملم", "مليمتر", "毫米"),
    "km": ("km", "kilometer", "kilometre", "كم", "كيلومتر", "公里"),
    "ft": ("ft", "foot", "feet", "قدم", "英尺"),
    "m2": ("m2", "sqm", "sq m", "sq.m", "square meter", "square meters", "square metre", "square metres", "متر مربع", "امتار مربعه", "平方米", "平米", "平方"),
    "ft2": ("ft2", "sqft", "sq ft", "sq.ft", "square foot", "square feet", "平方英尺"),
    "m3": ("m3", "cbm", "cubic meter", "cubic meters", "cubic metre", "cubic metres", "متر مكعب", "امتار مكعبه", "立方米", "立方"),
    "liter": ("l", "lt", "ltr", "liter", "liters", "litre", "litres", "لتر", "لترات", "升"),
    "ml": ("ml", "milliliter", "millilitre", "مل", "مليلتر", "毫升"),
    "gallon": ("gallon", "gallons", "gal", "جالون", "加仑"),
}

_UNIT_LOOKUP: dict[str, str] = {}
for _canon, _sps in _UNIT_SPELLINGS.items():
    for _sp in _sps:
        _UNIT_LOOKUP[_fold(_sp)] = _canon

_IS_AR = re.compile(r"[؀-ۿ]")
_IS_CJK = re.compile(r"[㐀-鿿豈-﫿]")


def _unit_alternation(prefix: bool = True) -> re.Pattern[str]:
    forms = sorted(_UNIT_LOOKUP, key=len, reverse=True)
    parts = []
    for f in forms:
        esc = re.escape(f).replace(r"\ ", r"\s+")
        if _IS_CJK.search(f):
            parts.append(esc)
        elif _IS_AR.search(f):
            parts.append(rf"(?<![\u0600-\u06ff])(?:لل|ل|ال)?{esc}(?![\u0600-\u06ff])" if prefix else rf"{esc}(?![\u0600-\u06ff])")
        else:
            parts.append(rf"(?<![a-z0-9]){esc}(?![a-z])")
    return re.compile("(?:" + "|".join(parts) + ")")


_UNIT_RE = _unit_alternation()
_UNIT_SRC = _UNIT_RE.pattern
_UNIT_BARE_SRC = _unit_alternation(prefix=False).pattern  # after an explicit Arabic ل / لل / لكل


def normalize_unit(text: object) -> str | None:
    """'Pieces' / 件 / 套 / 吨 / قطعة / للطن / 'per set' / m² -> canonical unit, or None when unknown."""
    s = _fold(text).strip()
    s = re.sub(r"^(?:per|/|each|every|每|لكل|for)\s*", "", s).strip(" .:/")
    s = re.sub(r"^\d+\s*", "", s)
    if not s:
        return None
    if s in _UNIT_LOOKUP:
        return _UNIT_LOOKUP[s]
    m = _UNIT_RE.fullmatch(s)
    if m:
        core = re.sub(r"^(?:لل|ل|ال)(?=[؀-ۿ])", "", s)
        return _UNIT_LOOKUP.get(re.sub(r"\s+", " ", core)) or _UNIT_LOOKUP.get(re.sub(r"\s+", " ", s))
    return None


def unit_dimension(unit: str) -> str | None:
    info = _UNIT_INFO.get(unit)
    return info[0] if info else None


class UnitConversionError(ValueError):
    """Raised instead of guessing (per-set vs per-piece, per-carton, cross-dimension ...)."""


def convert_unit_price(price: Decimal, src: str, dst: str) -> Decimal:
    """Price per ``src`` -> price per ``dst`` (e.g. per ton -> per kg = /1000). Same dimension only."""
    if src == dst:
        return price
    a, b = _UNIT_INFO.get(src), _UNIT_INFO.get(dst)
    if not a or not b:
        raise UnitConversionError(f"unknown unit: {src if not a else dst}")
    if a[0] != b[0] or a[1] is None or b[1] is None:
        raise UnitConversionError(f"cannot convert per-{src} to per-{dst} without pack size")
    return price * b[1] / a[1]


# --------------------------------------------------------------------------------------- currency
_CCY_WORDS: dict[str, str] = {
    "us$": "USD", "usd": "USD", "دولار": "USD", "دولارا": "USD", "美元": "USD", "美金": "USD", "dollar": "USD", "dollars": "USD",
    "cn¥": "CNY", "cny": "CNY", "rmb": "CNY", "元": "CNY", "人民币": "CNY", "圆": "CNY", "يوان": "CNY", "yuan": "CNY",
    "jp¥": "JPY", "jpy": "JPY", "円": "JPY", "日元": "JPY", "ين": "JPY", "yen": "JPY",
    "eur": "EUR", "€": "EUR", "euro": "EUR", "euros": "EUR", "يورو": "EUR", "欧元": "EUR",
    "gbp": "GBP", "£": "GBP", "جنيه استرليني": "GBP", "英镑": "GBP",
    "iqd": "IQD", "د.ع": "IQD", "دينار عراقي": "IQD",
    "aed": "AED", "د.ا": "AED", "درهم اماراتي": "AED",
    "sar": "SAR", "ر.س": "SAR", "ريال سعودي": "SAR",
    "kwd": "KWD", "دينار كويتي": "KWD",
    "egp": "EGP", "جنيه مصري": "EGP",
    "inr": "INR", "₹": "INR", "try": "TRY", "₺": "TRY", "krw": "KRW", "₩": "KRW",
    "cad": "CAD", "c$": "CAD", "ca$": "CAD", "aud": "AUD", "a$": "AUD", "au$": "AUD",
    "hkd": "HKD", "hk$": "HKD", "twd": "TWD", "nt$": "TWD", "sgd": "SGD", "s$": "SGD",
    "$": "USD",  # documented default for the bare dollar sign
}
# words that name several currencies: never resolved without extra evidence
_CCY_AMBIGUOUS: dict[str, tuple[str, ...]] = {
    "¥": ("CNY", "JPY"),
    "دينار": ("IQD", "KWD", "JOD", "DZD", "TND", "BHD", "LYD"),
    "ريال": ("SAR", "QAR", "OMR", "YER", "IRR"),
    "درهم": ("AED", "MAD"),
    "جنيه": ("EGP", "GBP", "SDG"),
}
_COUNTRY_YEN = {"CN": "CNY", "HK": "CNY", "JP": "JPY"}


def _ccy_regex() -> re.Pattern[str]:
    keys = sorted([*_CCY_WORDS, *_CCY_AMBIGUOUS], key=len, reverse=True)
    parts = []
    for k in keys:
        esc = re.escape(_fold(k))
        if _IS_CJK.search(k):
            parts.append(esc)
        elif _IS_AR.search(k):
            parts.append(rf"(?<![؀-ۿ]){esc}(?![؀-ۿ])")
        elif k.isascii() and k.replace(" ", "").isalpha():
            parts.append(rf"(?<![a-z]){esc}(?![a-z])")
        else:
            parts.append(esc)
    return re.compile("|".join(parts))


_CCY_RE = _ccy_regex()
_CCY_FOLDED = {_fold(k): v for k, v in _CCY_WORDS.items()}
_CCY_AMBIG_FOLDED = {_fold(k): v for k, v in _CCY_AMBIGUOUS.items()}


def detect_currency_ex(text: object, country: str | None = None) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    """-> (code | None, candidates, flags). Ambiguous words ('¥', 'دينار') resolve only by other evidence.

    Evidence for '¥': an explicit CNY/JPY marker elsewhere in the text, else ``country`` ('CN'/'JP').
    Several different currencies in one text -> (None, candidates, ('ambiguous_currency_mixed',)).
    """
    s = _fold(text)
    found: list[str] = []
    ambiguous: list[tuple[str, ...]] = []
    for m in _CCY_RE.finditer(s):
        tok = m.group(0)
        if tok in _CCY_FOLDED:
            found.append(_CCY_FOLDED[tok])
        elif tok in _CCY_AMBIG_FOLDED:
            ambiguous.append(_CCY_AMBIG_FOLDED[tok])
    explicit = list(dict.fromkeys(found))
    flags: list[str] = []
    # '$' alongside a more specific dollar marker ("US$") is the same token; collapse exact duplicates only
    if len(explicit) > 1:
        return None, tuple(explicit), ("ambiguous_currency_mixed",)
    if ambiguous:
        cands = ambiguous[0]
        hit = [c for c in cands if c in explicit]
        if explicit and hit:
            return hit[0], (hit[0],), tuple(flags)
        if explicit and not hit:
            return None, (*explicit, *cands), ("ambiguous_currency_mixed",)
        if cands == ("CNY", "JPY") and country:
            r = _COUNTRY_YEN.get(country.upper())
            if r:
                return r, (r,), ("currency_from_country",)
        return None, cands, ("ambiguous_currency_symbol",)
    if explicit:
        return explicit[0], (explicit[0],), tuple(flags)
    return None, (), ()


# --------------------------------------------------------------------------------------- numbers
_NUM = r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?(?![\d])|\d+(?:[.,]\d+)?"
_NUM_RE = re.compile(_NUM)


def parse_number(raw: str) -> tuple[Decimal | None, tuple[str, ...]]:
    """'1,234.50' / '1.234,50' / '12,5' / '12.500' -> (Decimal, flags). Withholds nothing but flags real ambiguity.

    Convention: a lone comma followed by exactly three digits is a thousands separator ('1,234' = 1234);
    a lone dot followed by three digits after a non-zero integer part is ambiguous ('12.500') and returned literally.
    """
    s = raw.strip()
    flags: list[str] = []
    try:
        if "." in s and "," in s:
            dec_sep = "." if s.rfind(".") > s.rfind(",") else ","
            thou = "," if dec_sep == "." else "."
            return Decimal(s.replace(thou, "").replace(dec_sep, ".")), tuple(flags)
        for sep in (",", "."):
            if sep in s:
                n = s.count(sep)
                head, _, tail = s.rpartition(sep)
                if n > 1:
                    return Decimal(s.replace(sep, "")), tuple(flags)
                if len(tail) == 3:
                    if sep == ",":
                        return Decimal(head + tail), tuple(flags)
                    if head.lstrip("0") == "":
                        return Decimal(s), tuple(flags)
                    flags.append("ambiguous_number_separator")
                    return Decimal(s), tuple(flags)
                if sep == ",":
                    flags.append("decimal_comma")
                    return Decimal(head + "." + tail), tuple(flags)
                return Decimal(s), tuple(flags)
        return Decimal(s), tuple(flags)
    except InvalidOperation:
        return None, ("ambiguous_number",)


# --------------------------------------------------------------------------------------- price text
@dataclass(frozen=True)
class PriceTier:
    min_qty: int | None
    max_qty: int | None
    price_min: Decimal
    price_max: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {"min_qty": self.min_qty, "max_qty": self.max_qty, "price_min": str(self.price_min), "price_max": str(self.price_max)}


@dataclass
class ParsedPrice:
    tiers: list[PriceTier] = field(default_factory=list)
    currency: str | None = None
    currency_candidates: tuple[str, ...] = ()
    unit: str | None = None
    pack_qty: int | None = None
    moq: int | None = None
    is_from: bool = False
    is_up_to: bool = False
    flags: tuple[str, ...] = ()

    @property
    def price_min(self) -> Decimal | None:
        return min((t.price_min for t in self.tiers), default=None)

    @property
    def price_max(self) -> Decimal | None:
        return max((t.price_max for t in self.tiers), default=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "price_min": None if self.price_min is None else str(self.price_min),
            "price_max": None if self.price_max is None else str(self.price_max),
            "currency": self.currency,
            "currency_candidates": list(self.currency_candidates),
            "unit": self.unit,
            "pack_qty": self.pack_qty,
            "moq": self.moq,
            "is_from": self.is_from,
            "is_up_to": self.is_up_to,
            "tiers": [t.to_dict() for t in self.tiers],
            "flags": sorted(self.flags),
        }


_INT = r"(\d{1,3}(?:,\d{3})+|\d+)"
_DASH = r"(?:-|–|—|~|to|至|الي|إلى|الى)"
_OPEN_WORDS = r"(?:and\s+above|or\s+more|and\s+up|and\s+over|起|以上|فاكثر|وما\s*فوق|فما\s*فوق)"
_UN = rf"(?:{_UNIT_SRC})"
_QTY_RANGE = re.compile(rf"(?<![\d.,]){_INT}\s*{_DASH}\s*{_INT}\s*(\+)?\s*({_UN})")
_QTY_OPEN = [
    re.compile(rf"(?:≥|>=|>)\s*{_INT}\s*({_UN})?"),
    re.compile(rf"(?<![\d.,]){_INT}\s*\+\s*({_UN})?"),
    re.compile(rf"(?<![\d.,]){_INT}\s*({_UN})\s*{_OPEN_WORDS}"),
]
_MOQ = re.compile(
    rf"(?:moq|min(?:imum)?\.?\s*order(?:\s*quantity)?|min\.?\s*qty|起订量?|最小起订量?|الحد\s*الادني(?:\s*للطلب)?)\s*[:：=]?\s*{_INT}\s*({_UN})?"
)
_PACK = re.compile(rf"(?<![\d.,]){_INT}\s*({_UN})\s*(?:/|per|في|بال|每)\s*({_UN})")
_PACK_PAREN = re.compile(rf"\(\s*{_INT}\s*({_UN})\s*\)")
_FROM = re.compile(r"(?<![a-z])(?:from|starting\s+(?:at|from)|starts?\s+at|as\s+low\s+as|min(?:imum)?\s+price|ابتداء\s+من|يبدا\s+من|تبدا\s+من|بدءا\s+من)(?![a-z])|起价|起售|起(?=\s*$)")
_UP_TO = re.compile(r"(?<![a-z])(?:up\s+to|max(?:imum)?\s+price|حتي|يصل\s+الي)(?![a-z])|最高")
_FROM_AR = re.compile(r"(?<![؀-ۿ])من(?=\s*[\d$¥€£]|\s*\d)")
_PER = re.compile(rf"(?:/|\bper\b|每|(?<![؀-ۿ])لكل|(?<![؀-ۿ])ل(?=[؀-ۿ]))\s*(\d+\s*)?({_UN})")
_PER_PREFIXED_AR = re.compile(rf"(?<![\u0600-\u06ff])(?:لكل\s*|لل|ل)((?:{_UNIT_BARE_SRC}))")
_QTY_UNIT_IN_PRICE_CTX = re.compile(r"\s+")


def _to_int(s: str) -> int:
    return int(s.replace(",", ""))


def _canon_unit(tok: str | None) -> str | None:
    return normalize_unit(tok) if tok else None


def _segments(s: str, n_qty: int) -> list[str]:
    parts = [p for p in re.split(r"[;|\n]+", s) if p.strip()]
    if len(parts) == 1 and n_qty >= 2:
        parts = [p for p in re.split(r",\s+", s) if p.strip()]
    return parts


def _find_qty(seg: str, currency_re: re.Pattern[str]) -> tuple[int | None, int | None, str | None, str]:
    """Extract one quantity expression from the segment -> (min, max, unit, remaining_text)."""
    for m in _QTY_RANGE.finditer(seg):
        before = seg[max(0, m.start() - 4) : m.start()]
        if currency_re.search(before.rstrip()[-3:]) if before.strip() else False:
            continue
        lo, hi = _to_int(m.group(1)), _to_int(m.group(2))
        lo, hi = (lo, hi) if lo <= hi else (hi, lo)
        return lo, (None if m.group(3) else hi), _canon_unit(m.group(4)), seg[: m.start()] + " " + seg[m.end() :]
    for rx in _QTY_OPEN:
        m = rx.search(seg)
        if m:
            before = seg[max(0, m.start() - 4) : m.start()].strip()
            if before and currency_re.search(before[-3:]):
                continue
            return _to_int(m.group(1)), None, _canon_unit(m.group(2)), seg[: m.start()] + " " + seg[m.end() :]
    return None, None, None, seg


MAX_PRICE_TEXT = 500


def parse_price_text(text: object, country: str | None = None) -> ParsedPrice:
    """Parse supplier price text into tiers (MOQ ladder), currency, unit and flags. See module docstring."""
    raw = _fold(text).strip()[:MAX_PRICE_TEXT]  # bound regex work: supplier text is untrusted (some patterns are O(n^2))
    out = ParsedPrice()
    flags: list[str] = []
    if not raw:
        out.flags = ("no_price",)
        return out

    code, cands, cflags = detect_currency_ex(raw, country)
    out.currency, out.currency_candidates = code, cands
    flags += cflags

    moq_m = _MOQ.search(raw)
    if moq_m:
        out.moq = _to_int(moq_m.group(1))
        raw = raw[: moq_m.start()] + " ; " + raw[moq_m.end() :]

    n_qty = len(_QTY_RANGE.findall(raw)) + sum(len(rx.findall(raw)) for rx in _QTY_OPEN)
    units_seen: list[str] = []
    qty_units: list[str] = []
    tiers: list[PriceTier] = []

    for seg in _segments(raw, n_qty):
        lo_q, hi_q, q_unit, rest = _find_qty(seg, _CCY_RE)
        if q_unit:
            qty_units.append(q_unit)
        is_from = bool(_FROM.search(rest) or _FROM_AR.search(rest))
        is_up_to = bool(_UP_TO.search(rest))
        rest = _UP_TO.sub(" ", _FROM.sub(" ", _FROM_AR.sub(" ", rest)))
        pack = _PACK.search(rest)
        seg_unit: str | None = None
        if pack:
            inner, outer = _canon_unit(pack.group(2)), _canon_unit(pack.group(3))
            if inner == "pc" and outer in ("set", "carton", "bag", "box", "pallet", "roll", "pair"):
                out.pack_qty = _to_int(pack.group(1))
                seg_unit = outer
                rest = rest[: pack.start()] + " " + rest[pack.end() :]
        if seg_unit is None:
            per = _PER.search(rest)
            ar = _PER_PREFIXED_AR.search(rest)
            if per:
                seg_unit = _canon_unit(per.group(2))
                rest = rest[: per.start()] + " " + rest[per.end() :]
            elif ar:
                seg_unit = _canon_unit(ar.group(1))
                rest = rest[: ar.start()] + " " + rest[ar.end() :]
        if seg_unit in ("set", "carton", "bag", "box", "pallet", "roll"):
            pp = _PACK_PAREN.search(rest)
            if pp and _canon_unit(pp.group(2)) == "pc":
                out.pack_qty = _to_int(pp.group(1))
                rest = rest[: pp.start()] + " " + rest[pp.end() :]
        if seg_unit:
            units_seen.append(seg_unit)

        cleaned = _CCY_RE.sub(" ", rest)
        nums = [(m.group(0), m.start(), m.end()) for m in _NUM_RE.finditer(cleaned)]
        if not nums:
            continue
        # range 'a - b' between two numbers
        if len(nums) == 2 and re.fullmatch(rf"\s*{_DASH}\s*", cleaned[nums[0][2] : nums[1][1]]):
            a, fa = parse_number(nums[0][0])
            b, fb = parse_number(nums[1][0])
            flags += [*fa, *fb]
            if a is None or b is None:
                flags.append("ambiguous_number")
                continue
            if a > b:
                a, b = b, a
                flags.append("reversed_range")
        elif len(nums) == 1:
            a, fa = parse_number(nums[0][0])
            flags += fa
            if a is None:
                flags.append("ambiguous_number")
                continue
            b = a
        else:
            flags.append("ambiguous_multiple_numbers")
            continue
        if a <= 0:
            flags.append("non_positive_price")
            continue
        if is_from:
            out.is_from = True
            b = a  # open-ended: only the lower bound is known
        if is_up_to:
            out.is_up_to = True
        tiers.append(PriceTier(lo_q, hi_q, a, b))

    if not tiers:
        out.flags = tuple(dict.fromkeys([*flags, "no_price"]))
        return out

    # -- unit: price unit, else infer from the quantity unit (flagged)
    uniq = list(dict.fromkeys(units_seen))
    if len(uniq) > 1:
        flags.append("ambiguous_mixed_units")
    elif uniq:
        out.unit = uniq[0]
    elif qty_units and len(set(qty_units)) == 1:
        out.unit = qty_units[0]
        flags.append("unit_inferred_from_qty")
    if out.unit and qty_units and any(u != out.unit for u in qty_units):
        flags.append("unit_mismatch")
    if out.unit == "set" and not out.pack_qty:
        flags.append("per_set_pack_unknown")

    # -- tier consistency
    tiers.sort(key=lambda t: (t.min_qty is None, t.min_qty or 0))
    if len(tiers) > 1:
        if any(t.min_qty is None for t in tiers):
            flags.append("ambiguous_tier_without_qty")
        for prev, nxt in zip(tiers, tiers[1:], strict=False):
            if prev.max_qty is not None and nxt.min_qty is not None:
                if nxt.min_qty <= prev.max_qty:
                    flags.append("overlapping_tiers")
                elif nxt.min_qty > prev.max_qty + 1:
                    flags.append("tier_gap")
            if nxt.price_min > prev.price_max:
                flags.append("non_monotonic_tiers")
    if out.moq is None and tiers[0].min_qty:
        out.moq = tiers[0].min_qty
    out.tiers = tiers
    out.flags = tuple(dict.fromkeys(flags))
    return out


# --------------------------------------------------------------------------------------- condition
_COND_NEW = re.compile(r"(?<![a-z])(?:brand[\s-]*new|new|never\s+used|mint)(?![a-z])|全新|新品|جديد|جديده|جديدة")
_COND_USED = re.compile(r"(?<![a-z])(?:used|second[\s-]*hand|pre[\s-]*owned|pre[\s-]*loved)(?![a-z])|二手|旧|مستعمل|مستعمله|مستخدم|مستخدمه")
_COND_REFURB = re.compile(r"(?<![a-z])(?:refurbished|refurb|reconditioned|renovated|remanufactured|overhauled|rebuilt)(?![a-z])|翻新|再制造|مجدد|مجدده|معاد\s*تاهيل|معاد\s*تصنيع")
_COND_LIKE_NEW = re.compile(r"(?<![a-z])(?:like[\s-]*new|almost\s+new|nearly\s+new|barely\s+used|lightly\s+used|unused|n\.?o\.?s\.?|new\s+old\s+stock)(?![a-z])|\d{2}\s*%\s*new|九成新|九五新|شبه\s*جديد|كالجديد|غير\s*مستعمل|غير\s*مستخدم")
_NEGATED_NEW = re.compile(r"(?<![a-z])(?:not|non|isn'?t)[\s-]+(?:brand[\s-]*)?new(?![a-z])|غير\s*جديد|ليس\s*جديد|不是全新|非全新")


def parse_condition(text: object) -> tuple[str | None, tuple[str, ...]]:
    """Free text -> ('new'|'used'|'refurbished'|None, flags). 'like new' / 'unused' / conflicts are NOT guessed."""
    s = _fold(text)
    flags: list[str] = []
    like = _COND_LIKE_NEW.search(s)
    if like:
        s = s[: like.start()] + " " + s[like.end() :]
        flags.append("ambiguous_like_new")
    negated = _NEGATED_NEW.search(s)
    if negated:
        s = s[: negated.start()] + " " + s[negated.end() :]
    found = []
    if _COND_REFURB.search(s):
        found.append("refurbished")
        s = _COND_REFURB.sub(" ", s)  # 'renovated' must not also read as a stray 'new'
    if _COND_USED.search(s):
        found.append("used")
    if _COND_NEW.search(s):
        found.append("new")
    if negated and "used" not in found and "refurbished" not in found:
        flags.append("ambiguous_negated_new")
        return None, tuple(flags)
    if len(found) == 1 and not like:
        return found[0], tuple(flags)
    if found and like:
        flags.append("ambiguous_conflicting_condition")
        return None, tuple(dict.fromkeys(flags))
    if len(found) > 1:
        return None, ("ambiguous_conflicting_condition",)
    return None, tuple(flags)


# --------------------------------------------------------------------------------------- year
_Y = r"((?:19|20)\d{2})"
_YEAR_LABELED = [
    re.compile(rf"(?:year\s+of\s+(?:manufacture|production|make|build)|manufactur(?:ed|ing)(?:\s+(?:in|year))?|made\s+in|built(?:\s+in)?|mfg\.?|mfd\.?|produced(?:\s+in)?|production\s+year|model\s+year|year)\s*[:：=\-]?\s*{_Y}(?!\d)"),
    re.compile(rf"(?<!\d){_Y}\s*(?:年\s*(?:出厂|生产|制造|产)?|year\s+(?:model|built|made)|year(?!\s*s?\s*(?:old|warranty))|model|mfg|made|built)"),
    re.compile(rf"(?:سنه\s*الصنع|سنه\s*الانتاج|عام\s*الصنع|عام\s*الانتاج|صنع\s*(?:في\s*)?(?:سنه|عام)?|موديل|سنه|عام)\s*[:：=\-]?\s*{_Y}(?!\d)"),
    re.compile(rf"(?:出厂年份|生产年份|制造年份|出厂|生产日期)\s*[:：=\-]?\s*{_Y}"),
]
_YEAR_RANGE = re.compile(rf"(?<!\d){_Y}\s*(?:-|–|~|to|الي|至)\s*{_Y}(?!\d)")


def parse_year(text: object, now_year: int | None = None) -> tuple[int | None, tuple[str, ...]]:
    """Year of manufacture from labeled text ('2015 year', 'year: 2015', '2015年', 'موديل 2015').

    A bare 4-digit number is never taken (could be a model number); ranges, several distinct labeled years,
    and implausible years (< 1950 or after next year) are withheld with an ``ambiguous_`` / ``implausible_`` flag.
    """
    s = _fold(text)
    ny = now_year if now_year is not None else date.today().year
    if _YEAR_RANGE.search(s):
        return None, ("ambiguous_year_range",)
    years: list[int] = []
    for rx in _YEAR_LABELED:
        years += [int(m.group(1)) for m in rx.finditer(s)]
    uniq = sorted(set(years))
    if not uniq:
        return None, ()
    if len(uniq) > 1:
        return None, ("ambiguous_multiple_years",)
    y = uniq[0]
    if y < 1950 or y > ny + 1:
        return None, ("implausible_year",)
    return y, ()
