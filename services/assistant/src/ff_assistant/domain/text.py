"""Arabic/English text normalization and tokenization (pure functions, no I/O).

Two parallel strings are produced from the raw user text:

* ``clean`` — NFKC-normalized, diacritics/tatweel removed, Arabic-Indic digits and Arabic
  punctuation mapped to ASCII. Keeps the user's spelling (hamza, ta marbuta, case); used for
  surface forms such as search keywords and references.
* ``norm`` — ``clean`` folded character-by-character (alef/ya/ta-marbuta/hamza-carrier
  unification, Persian/Iraqi letters, lower-case). Same length as ``clean`` so token offsets
  are shared; used for every lexicon/gazetteer lookup.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

_DIACRITICS_RE = re.compile(
    "[ؐ-ًؚ-ٰٟۖ-ۜ۟-۪ۨ-ۭـ]"
)

_CHAR_MAP: dict[int, str | None] = {
    # Arabic-Indic (٠-٩) and Eastern Arabic-Indic / Persian (۰-۹) digits.
    **{0x0660 + i: str(i) for i in range(10)},
    **{0x06F0 + i: str(i) for i in range(10)},
    0x066B: ".",  # Arabic decimal separator
    0x066C: ",",  # Arabic thousands separator
    0x060C: ",",  # Arabic comma
    0x061B: ";",  # Arabic semicolon
    0x061F: "?",  # Arabic question mark
    0x066A: "%",  # Arabic percent sign
    0x200C: " ",  # zero-width non-joiner
    0x200D: None,  # zero-width joiner
    0x200E: None,  # left-to-right mark
    0x200F: None,  # right-to-left mark
    0x061C: None,  # Arabic letter mark
    0x00A0: " ",  # no-break space
    0x2013: "-",  # en dash
    0x2014: "-",  # em dash
    0x2212: "-",  # minus sign
}

# Character-for-character folding (must stay length preserving).
_FOLD_MAP = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ٲ": "ا",
        "ٳ": "ا",
        "ى": "ي",
        "ی": "ي",
        "ې": "ي",
        "ئ": "ي",
        "ة": "ه",
        "ۃ": "ه",
        "ۀ": "ه",
        "ھ": "ه",
        "ؤ": "و",
        "ک": "ك",
        "ڪ": "ك",
        "گ": "ك",  # Iraqi "g" (شگد → شكد)
        "چ": "ك",  # Iraqi "ch" usually stands for ك (چم → كم)
        "پ": "ب",
        "ڤ": "ف",
        "ژ": "ز",
    }
)

_ARABIC_LETTER_RE = re.compile("[ء-يٱ-ۓ]")
_LATIN_LETTER_RE = re.compile("[A-Za-z]")
_SPACES_RE = re.compile(r"\s+")

TokenKind = Literal["num", "word", "sym"]

_TOKEN_RE = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)*)"
    r"|(?P<word>[^\W\d_]+(?:['’-][^\W\d_]+)*)"
    r"|(?P<sym>[$€£¥%+\-/?])"
)


def clean_text(raw: str) -> str:
    """NFKC + strip diacritics/tatweel + ASCII digits/punctuation + collapsed spaces."""
    text = unicodedata.normalize("NFKC", raw)
    text = _DIACRITICS_RE.sub("", text)
    text = text.translate(_CHAR_MAP)
    return _SPACES_RE.sub(" ", text).strip()


def fold(clean: str) -> str:
    """Letter-unify and lower-case ``clean`` without changing its length."""
    folded = clean.translate(_FOLD_MAP)
    out = []
    for ch in folded:
        low = ch.lower()
        out.append(low if len(low) == 1 else ch)
    return "".join(out)


def normalize(raw: str) -> str:
    """Full normalization used for lexicon keys and comparisons."""
    return fold(clean_text(raw))


def detect_language(clean: str) -> Literal["ar", "en"]:
    arabic = len(_ARABIC_LETTER_RE.findall(clean))
    latin = len(_LATIN_LETTER_RE.findall(clean))
    return "en" if latin > arabic else "ar"


def is_arabic(word: str) -> bool:
    return bool(_ARABIC_LETTER_RE.search(word))


@dataclass(frozen=True, slots=True)
class Token:
    index: int
    kind: TokenKind
    norm: str
    surface: str
    start: int
    end: int

    @property
    def is_word(self) -> bool:
        return self.kind == "word"

    @property
    def is_num(self) -> bool:
        return self.kind == "num"


def tokenize(clean: str, norm: str) -> list[Token]:
    """Split into number / word / symbol tokens. ``clean`` and ``norm`` must be aligned."""
    if len(clean) != len(norm):  # pragma: no cover - guarded by fold()
        raise ValueError("clean and norm strings must be aligned")
    tokens: list[Token] = []
    for match in _TOKEN_RE.finditer(norm):
        kind: TokenKind = match.lastgroup  # type: ignore[assignment]
        start, end = match.span()
        tokens.append(
            Token(
                index=len(tokens),
                kind=kind,
                norm=match.group(),
                surface=clean[start:end],
                start=start,
                end=end,
            )
        )
    return tokens


# Attached Arabic proclitics, longest first. Values describe the grammatical role that matters
# to the parser: "to" (ل), "in" (ب), "and"/"so"/"like" (no direction).
CLITIC_PREFIXES: tuple[tuple[str, str], ...] = (
    ("وبال", "in"),
    ("وال", "the"),
    ("بال", "in"),
    ("فال", "the"),
    ("كال", "like"),
    ("ولل", "to"),
    ("لل", "to"),
    ("وب", "in"),
    ("ول", "to"),
    ("فب", "in"),
    ("فل", "to"),
    ("و", "and"),
    ("ف", "and"),
    ("ب", "in"),
    ("ل", "to"),
    ("ك", "like"),
)


def clitic_variants(word: str, min_stem: int = 3) -> list[tuple[str, str]]:
    """Return ``(role, stem)`` candidates for an Arabic word, the unprefixed form first.

    Each stem is also offered with the definite article re-attached, because "للبصره" is
    "ل" + "البصره" with the article's alef elided.
    """
    out: list[tuple[str, str]] = [("", word)]
    if not is_arabic(word):
        return out
    seen = {word}
    for prefix, role in CLITIC_PREFIXES:
        if word.startswith(prefix) and len(word) - len(prefix) >= min_stem:
            stem = word[len(prefix) :]
            for candidate in (stem, "ال" + stem):
                if candidate not in seen:
                    seen.add(candidate)
                    out.append((role, candidate))
    return out


def mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Replace the given spans with spaces (keeps offsets stable)."""
    if not spans:
        return text
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            chars[i] = " "
    return "".join(chars)
