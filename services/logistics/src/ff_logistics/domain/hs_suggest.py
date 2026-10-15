"""Keyword -> HS-heading suggestions (Arabic / English / Chinese). INDICATIVE ONLY, never an official classification.

Matching is plain token / substring comparison (no regex built from user input), input is capped at MAX_Q chars,
so cost is linear and ReDoS-safe. Data: data/hs_keywords.json.
"""
from dataclasses import dataclass
from functools import lru_cache

from .duties import load_json
from .hs import normalize, tokens

MAX_Q = 100
MAX_LIMIT = 20
NOTE = "indicative suggestion only, not an official classification; confirm with a customs broker"


@dataclass(frozen=True)
class _Entry:
    hs6: str
    description_en: str
    description_ar: str
    phrases: tuple[tuple[str, ...], ...]  # token sequences (en/ar)
    zh: tuple[str, ...]
    tok_set: frozenset[str]


@lru_cache(maxsize=1)
def _load() -> tuple[_Entry, ...]:
    out = []
    for it in load_json("hs_keywords.json")["items"]:
        kw = it["keywords"]
        phrases = tuple(p for p in (tuple(tokens(k)) for k in kw["en"] + kw["ar"]) if p)
        zh = tuple(normalize(k) for k in kw["zh"] if k)
        out.append(_Entry(it["hs6"], it["description_en"], it["description_ar"], phrases, zh,
                          frozenset(t for p in phrases for t in p if len(t) >= 3)))
    return tuple(out)


def _contains(hay: list[str], needle: tuple[str, ...]) -> bool:
    n = len(needle)
    return any(tuple(hay[i:i + n]) == needle for i in range(len(hay) - n + 1))


def _score(e: _Entry, q_norm: str, q_tokens: list[str]) -> float:
    s = 0.0
    for p in e.phrases:
        if _contains(q_tokens, p):
            s = max(s, 4.0 * len(p) + (4.0 if len(p) == len(q_tokens) else 0.0))
    for z in e.zh:
        if z in q_norm:
            s = max(s, 2.0 * len(z) + (4.0 if len(z) == len(q_norm.replace(" ", "")) else 0.0))
    if s == 0.0:  # weak: shared word only
        shared = sum(1 for t in set(q_tokens) if len(t) >= 3 and t in e.tok_set)
        s = float(shared)
    return s


def suggest_hs(text: str, limit: int = 5) -> list[dict]:
    """Ranked indicative HS6 suggestions for a free-text goods description. Empty/garbage -> []."""
    if not isinstance(text, str):
        return []
    q_norm = normalize(text[:MAX_Q]).strip()
    if not q_norm:
        return []
    q_tokens = tokens(q_norm)
    limit = max(1, min(int(limit), MAX_LIMIT))
    scored = []
    for e in _load():
        s = _score(e, q_norm, q_tokens)
        if s > 0:
            scored.append((s, e))
    scored.sort(key=lambda x: (-x[0], x[1].hs6))
    return [{"hs6": e.hs6, "description_en": e.description_en, "description_ar": e.description_ar,
             "confidence": "medium" if s >= 8.0 else "low", "note": NOTE}
            for s, e in scored[:limit]]
