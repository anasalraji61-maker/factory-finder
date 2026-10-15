"""Deterministic anti-spam primitives (pure: no I/O, no ML, no network).

* ``fingerprint`` -- normalized text (Arabic-aware, see ``moderation.normalize``: tashkeel/tatweel,
  alef-hamza, yaa, taa marbuta and Arabic-Indic digits are folded) -> (sha256 of the token stream,
  3-word shingle set).
* ``similarity`` -- exact hash match = 1.0, else Jaccard of the shingle sets.
* ``suspicious_signals`` -- contact/off-platform signals that the hard screening (``moderation.py``,
  which already *rejects* plain links, e-mails, phone numbers and messaging handles with 422) cannot
  prove: digits smuggled between letters, spelled-out phone numbers, "DM me" style solicitation and
  flooding (one token repeated). Such content is not rejected, it is queued for review.

Signals name the *kind* only; they never carry matched text.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from ff_feed.moderation import _AR_DIGITS, normalize

SHINGLE = 3

_DIGIT_WORDS = (
    "zero|oh|one|two|three|four|five|six|seven|eight|nine|"
    "صفر|واحد|اثنين|اثنان|اثنتين|ثلاثه|ثلاث|اربعه|اربع|خمسه|خمس|سته|ست|سبعه|سبع|ثمانيه|ثماني|تسعه|تسع"
)
_SPELLED_PHONE = re.compile(rf"(?:\b(?:{_DIGIT_WORDS})\b\s*){{7,}}")
# 9+ single digits each glued to the next by 1-2 non-space symbols/letters ("0o7o7_1,2..."): the plain
# phone regex in moderation.py only tolerates whitespace and -(). Dimensions like "12.5x3.4x5.6" do not
# match because digits there are adjacent.
_GLUED_DIGITS = re.compile(r"(?:\d[^\d\s]{1,2}){8,}\d")
_SOLICIT = re.compile(
    r"\b(?:dm|pm|inbox)\s+me\b|\bcontact\s+me\s+(?:privately|outside|off\s*platform)\b|"
    r"راسلني\s+(?:على\s+)?الخاص|كلمني\s+(?:على\s+)?الخاص|تواصل\s+معي\s+(?:على\s+)?الخاص|للتواصل\s+خاص",
    re.IGNORECASE,
)


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def _shingles(toks: list[str]) -> frozenset[str]:
    if len(toks) < SHINGLE:
        return frozenset({" ".join(toks)}) if toks else frozenset()
    return frozenset(" ".join(toks[i : i + SHINGLE]) for i in range(len(toks) - SHINGLE + 1))


class Fingerprint:
    __slots__ = ("digest", "shingles", "size")

    def __init__(self, text: str):
        toks = tokens(text)
        self.size = len(toks)
        self.digest = hashlib.sha256(" ".join(toks).encode()).hexdigest()
        self.shingles = _shingles(toks)


def fingerprint(text: str) -> Fingerprint:
    return Fingerprint(text)


def similarity(a: Fingerprint, b: Fingerprint) -> float:
    if not a.shingles or not b.shingles:
        return 0.0
    if a.digest == b.digest:
        return 1.0
    union = len(a.shingles | b.shingles)
    return len(a.shingles & b.shingles) / union if union else 0.0


def is_match(new: Fingerprint, old: Fingerprint, threshold: float, min_tokens: int) -> bool:
    """Exact (normalized) duplicate, or Jaccard >= threshold (0 = exact matches only). Texts shorter than
    ``min_tokens`` words never match ("thanks", "x"): short replies are legitimately repeated."""
    if new.size < min_tokens or old.size < min_tokens:
        return False
    if new.digest == old.digest:
        return True
    return threshold > 0 and similarity(new, old) >= threshold


def suspicious_signals(text: str) -> list[str]:
    """Kinds of suspicious content that were not strict contact details: ``obfuscated_phone``,
    ``solicitation``, ``flooding``. Deterministic and cheap (linear in the text)."""
    t = unicodedata.normalize("NFKC", text or "").translate(_AR_DIGITS)
    out: list[str] = []
    if _GLUED_DIGITS.search(t) or _SPELLED_PHONE.search(normalize(t)):
        out.append("obfuscated_phone")
    if _SOLICIT.search(t) or _SOLICIT.search(normalize(t)):
        out.append("solicitation")
    toks = tokens(t)
    if re.search(r"(.)\1{14,}", t) or (len(toks) >= 8 and max(toks.count(x) for x in set(toks)) >= max(8, len(toks) * 3 // 5)):
        out.append("flooding")
    return out
