"""Dictionary-driven segmentation of Chinese runs (no spaces in Chinese text).

Every Han term that appears in ``lexicon_ml.RAW`` or ``data/aliases_ml.json`` is a vocabulary word;
a Han run is split greedily longest-first, and unknown stretches stay together as one token
(so unknown product names survive as a single keyword). Pure and deterministic.
"""

from __future__ import annotations

import re
from functools import cache

from ff_assistant.data import load_json
from ff_assistant.domain.lexicon_ml import RAW

HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")
_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_NUM_UNIT_RE = re.compile(r"([一二两三四五六七八九十百]+)(?=吨|公吨|公斤|千克|个|件|台|套|只|张|条|柜|集装箱|货柜|米|升)")


def _strings(node: object):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _strings(v)


@cache
def vocab() -> tuple[frozenset[str], int]:
    words: set[str] = set()
    for src in (RAW, load_json("aliases_ml.json")):
        for s in _strings(src):
            words.update(HAN_RE.findall(s))
    return frozenset(words), max((len(w) for w in words), default=1)


def segment(text: str) -> str:
    """Insert spaces around/inside Han runs so each known term (or unknown stretch) is one token."""
    if not HAN_RE.search(text):
        return text
    words, longest = vocab()

    def split(m: re.Match[str]) -> str:
        run, out, unknown, i = m.group(), [], "", 0
        while i < len(run):
            for n in range(min(longest, len(run) - i), 0, -1):
                if run[i : i + n] in words:
                    if unknown:
                        out.append(unknown)
                        unknown = ""
                    out.append(run[i : i + n])
                    i += n
                    break
            else:
                unknown += run[i]
                i += 1
        if unknown:
            out.append(unknown)
        return " " + " ".join(out) + " "

    return HAN_RE.sub(split, text)


def _han_int(s: str) -> int | None:
    if "百" in s:
        head, _, tail = s.partition("百")
        hundreds = _NUM.get(head, 1 if head == "" else None)
        rest = _han_int(tail) if tail else 0
        if hundreds is None or rest is None:
            return None
        return hundreds * 100 + rest
    if "十" in s:
        head, _, tail = s.partition("十")
        tens = _NUM.get(head, 1 if head == "" else None)
        ones = _NUM.get(tail, 0 if tail == "" else None)
        if tens is None or ones is None:
            return None
        return tens * 10 + ones
    return _NUM.get(s) if len(s) == 1 else None


def digits(text: str) -> str:
    """Chinese numerals directly before a unit ('五吨', '二十五个') become ASCII digits."""
    return _NUM_UNIT_RE.sub(lambda m: str(v) if (v := _han_int(m.group(1))) is not None else m.group(0), text)
