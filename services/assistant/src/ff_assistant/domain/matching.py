"""Phrase lexicons over normalized tokens: longest match, Arabic-clitic aware.

Every lexicon key and every input token goes through the same canonicalization
(:func:`canon`), so "المواد الأولية", "مواد اوليه" and "والمواد الاولية" all hit the same entry.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from ff_assistant.domain.text import (
    CLITIC_PREFIXES,
    Token,
    clean_text,
    fold,
    is_arabic,
    tokenize,
)

T = TypeVar("T")

# Proclitic clusters that contain the (elided) definite article: a 2-letter stem is allowed
# after them ("للطن" → "طن"), while bare one-letter clitics need a 3-letter stem ("وطن" stays).
_ARTICLE_PREFIXES = frozenset({"وبال", "وال", "بال", "فال", "كال", "ولل", "لل"})


def canon(word: str) -> str:
    """Drop the Arabic definite article when a stem of 3+ letters remains."""
    if len(word) >= 5 and word.startswith("ال") and is_arabic(word):
        return word[2:]
    return word


def lookup_forms(word: str) -> list[tuple[str, str]]:
    """``(clitic_role, canonical_form)`` candidates for a folded token; bare form first."""
    first = canon(word)
    forms = [("", first)]
    if not is_arabic(word):
        return forms
    seen = {first}
    for prefix, role in CLITIC_PREFIXES:
        if not word.startswith(prefix):
            continue
        stem = word[len(prefix) :]
        min_len = 2 if prefix in _ARTICLE_PREFIXES else 3
        if len(stem) < min_len:
            continue
        form = canon(stem)
        if form not in seen:
            seen.add(form)
            forms.append((role, form))
    return forms


def phrase_key(phrase: str) -> tuple[str, ...]:
    clean = clean_text(phrase)
    return tuple(canon(t.norm) for t in tokenize(clean, fold(clean)))


@dataclass(frozen=True, slots=True)
class PhraseMatch[V]:
    start: int
    end: int
    value: V
    role: str = ""  # clitic role attached to the first token ("to", "in", "and", ...)

    @property
    def length(self) -> int:
        return self.end - self.start


class PhraseIndex[V]:
    """Maps token sequences to values; matching is longest-first."""

    def __init__(self, entries: Iterable[tuple[str, V]] = ()) -> None:
        self._index: dict[str, list[tuple[tuple[str, ...], V]]] = {}
        for phrase, value in entries:
            self.add(phrase, value)

    def add(self, phrase: str, value: V) -> None:
        key = phrase_key(phrase)
        if not key:
            raise ValueError(f"empty lexicon phrase: {phrase!r}")
        bucket = self._index.setdefault(key[0], [])
        if any(existing == key for existing, _ in bucket):
            return  # first definition wins
        bucket.append((key, value))
        bucket.sort(key=lambda item: -len(item[0]))

    def match_at(
        self,
        tokens: Sequence[Token],
        i: int,
        consumed: Sequence[bool] | None = None,
        *,
        clitics: bool = True,
    ) -> PhraseMatch[V] | None:
        if consumed is not None and consumed[i]:
            return None
        forms = lookup_forms(tokens[i].norm) if clitics else [("", canon(tokens[i].norm))]
        best: PhraseMatch[V] | None = None
        for role, form in forms:
            for key, value in self._index.get(form, ()):
                size = len(key)
                if best is not None and size <= best.length:
                    break
                if self._tail_matches(tokens, i, key, consumed):
                    best = PhraseMatch(i, i + size, value, role)
                    break
        return best

    @staticmethod
    def _tail_matches(
        tokens: Sequence[Token],
        i: int,
        key: tuple[str, ...],
        consumed: Sequence[bool] | None,
    ) -> bool:
        if i + len(key) > len(tokens):
            return False
        for offset in range(1, len(key)):
            tok = tokens[i + offset]
            if consumed is not None and consumed[i + offset]:
                return False
            if canon(tok.norm) != key[offset]:
                return False
        return True

    def find_all(
        self,
        tokens: Sequence[Token],
        consumed: Sequence[bool] | None = None,
        *,
        clitics: bool = True,
    ) -> list[PhraseMatch[V]]:
        out: list[PhraseMatch[V]] = []
        i = 0
        while i < len(tokens):
            match = self.match_at(tokens, i, consumed, clitics=clitics)
            if match is None:
                i += 1
            else:
                out.append(match)
                i = match.end
        return out

    def lookup(self, word: str, *, clitics: bool = False) -> V | None:
        """Single-token lookup of an already folded word."""
        forms = lookup_forms(word) if clitics else [("", canon(word))]
        for _, form in forms:
            for key, value in self._index.get(form, ()):
                if len(key) == 1:
                    return value
        return None


def word_set(words: Iterable[str]) -> frozenset[str]:
    """Canonical single-token set (multi-word entries are rejected)."""
    out: set[str] = set()
    for word in words:
        key = phrase_key(word)
        if len(key) != 1:
            raise ValueError(f"word_set entries must be single tokens: {word!r}")
        out.add(key[0])
    return frozenset(out)


def in_set(word: str, words: frozenset[str], *, clitics: bool = False) -> bool:
    forms = lookup_forms(word) if clitics else [("", canon(word))]
    return any(form in words for _, form in forms)
