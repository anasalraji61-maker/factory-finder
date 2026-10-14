"""HS-code finder over a curated, indicative dataset (data/hs_codes.json). Pure, no I/O after load."""
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from .duties import load_json

_AR_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})
_TOKEN = re.compile(r"[0-9a-zء-ي]+")


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower().replace("ـ", "")
    t = "".join(ch for ch in t if not unicodedata.category(ch).startswith("M"))  # Arabic diacritics
    return t.translate(_AR_MAP)


def _stem(tok: str) -> str:
    if re.fullmatch(r"[a-z]+", tok):
        if len(tok) > 4 and tok.endswith("ies"):
            return tok[:-3] + "y"
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            return tok[:-1]
        return tok
    if len(tok) > 4 and tok.startswith("ال"):
        return tok[2:]
    return tok


def tokens(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(normalize(text))]


@dataclass(frozen=True)
class HsEntry:
    code: str
    chapter: str
    description_en: str
    description_ar: str
    keywords: tuple[str, ...]
    kw_tokens: frozenset[str]
    desc_tokens: frozenset[str]


@lru_cache(maxsize=1)
def dataset() -> tuple[dict, dict[str, HsEntry]]:
    raw = load_json("hs_codes.json")
    entries: dict[str, HsEntry] = {}
    for it in raw["items"]:
        kws = tuple(it["keywords"])
        entries[it["code"]] = HsEntry(
            it["code"], it["chapter"], it["description_en"], it["description_ar"], kws,
            frozenset(t for k in kws for t in tokens(k)),
            frozenset(tokens(it["description_en"]) + tokens(it["description_ar"])))
    return {"note": raw["note"], "version": raw["version"]}, entries


def normalize_code(code: str) -> str | None:
    digits = re.sub(r"[.\s-]", "", code)
    if not digits.isdigit() or not 6 <= len(digits) <= 10:
        return None
    return digits[:6]


def get(code: str) -> HsEntry | None:
    key = normalize_code(code)
    return dataset()[1].get(key) if key else None


def search(q: str, limit: int = 10) -> list[HsEntry]:
    entries = dataset()[1]
    compact = re.sub(r"[.\s-]", "", q.strip())
    if compact.isdigit():
        hits = [e for c, e in sorted(entries.items()) if c.startswith(compact[:6])]
        return hits[:limit]
    toks = tokens(q)
    if not toks:
        return []
    scored: list[tuple[float, str, HsEntry]] = []
    for code, e in entries.items():
        total, matched = 0.0, 0
        for t in toks:
            if t in e.kw_tokens:
                s = 3.0
            elif t in e.desc_tokens:
                s = 2.0
            elif len(t) >= 3 and any(x.startswith(t) for x in e.kw_tokens | e.desc_tokens):
                s = 1.0
            else:
                continue
            total += s
            matched += 1
        if matched:
            scored.append((total + matched * 2.0 + (4.0 if matched == len(toks) else 0.0), code, e))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [e for _, _, e in scored[:limit]]


def duty_hint(duties: dict, country: str, chapter: str) -> float | None:
    c = duties["countries"].get(country)
    if c is None or chapter not in c["chapters"]:
        return None
    return float(c["chapters"][chapter])


def to_item(e: HsEntry, duties: dict, country: str) -> dict:
    return {"code": e.code, "chapter": e.chapter, "description_en": e.description_en,
            "description_ar": e.description_ar,
            "typical_duty_percent_hint": duty_hint(duties, country, e.chapter),
            "keywords": list(e.keywords)}
