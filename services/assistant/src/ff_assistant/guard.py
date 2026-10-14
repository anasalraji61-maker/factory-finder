"""Prompt-injection guardrails: third-party text (listing titles, supplier names, carrier events,
HS descriptions, trust notes) is DATA. It is cleaned of control/bidi characters, markup and
instruction-like phrases, length-capped, and only ever interpolated into answers and cards. It is
never placed in an LLM system prompt, never parsed for intents, and never used to pick a tool,
a user id or a downstream URL.
"""

from __future__ import annotations

import re

from ff_assistant.domain.models import Listing, TrustScore

FILTERED = "[filtered]"
WARNING = "untrusted_text_filtered"

_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩﻿]")
_MD_LINK = re.compile(r"!?\[([^\]]{0,200})\]\([^)]{0,500}\)")
_TAG = re.compile(r"<[^>]{0,300}>")
_FENCE = re.compile(r"`{3,}|~{3,}")
_INJECT = re.compile(
    r"(?i)(?:ignore|disregard|forget|override)\s+(?:all\s+|any\s+|the\s+|your\s+|my\s+)*(?:previous|prior|above|earlier|system|these)?\s*"
    r"(?:instructions?|rules?|prompts?|messages?|context|guidelines?)"
    r"|(?:reveal|show|print|leak|send|output)\s+(?:me\s+)?(?:the\s+|your\s+)?(?:system\s+prompt|api[- ]?keys?|tokens?|secrets?|passwords?)"
    r"|system\s*prompt|developer\s*message|\bnew\s+instructions?\b|\byou\s+are\s+now\b|\bact\s+as\b|\bpretend\s+to\b"
    r"|\b(?:system|assistant|user)\s*:|<\|[^|]{0,40}\|>|\[/?(?:inst|system)\]"
    r"|تجاهل\s+(?:كل\s+|جميع\s+)?(?:ال)?(?:تعليمات|اوامر|أوامر)|انس[ىَ]?\s+(?:كل\s+)?(?:ال)?تعليمات|تعليمات\s+(?:ال)?(?:نظام|جديدة)"
    r"|(?:انت|أنت)\s+(?:ال)?(?:ان|آن|الآن)|اكشف\s+(?:ال)?(?:مفتاح|رمز|سر)"
)


def clean(text: str | None, max_len: int = 120) -> tuple[str, bool]:
    """Return (safe single-line text, whether instruction-like content was removed)."""
    if not text:
        return "", False
    t = _MD_LINK.sub(r"\1", str(text))
    t = _TAG.sub(" ", t)
    t = _FENCE.sub(" ", t)
    t = _CTRL.sub(" ", t)
    t, n = _INJECT.subn(FILTERED, t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > max_len:
        t = t[: max_len - 1].rstrip() + "…"
    return t, n > 0


class Sanitizer:
    """Collects whether anything was filtered so the response can carry one warning."""

    def __init__(self) -> None:
        self.hit = False

    def text(self, value: str | None, max_len: int = 120) -> str:
        out, hit = clean(value, max_len)
        self.hit = self.hit or hit
        return out

    def opt(self, value: str | None, max_len: int = 120) -> str | None:
        return self.text(value, max_len) if value else None

    def listing(self, lst: Listing) -> Listing:
        sup = lst.supplier.model_copy(update={"name": self.text(lst.supplier.name, 80)})
        extras = {k: self.text(v, 300) for k, v in (lst.model_extra or {}).items() if isinstance(v, str) and k != "source_url"}
        update = {"title": self.text(lst.title, 160), "title_ar": self.opt(lst.title_ar, 160), "supplier": sup,
                  "category": self.opt(lst.category, 60), **extras}
        return lst.model_copy(update=update)

    def trust(self, t: TrustScore) -> TrustScore:
        factors = [f.model_copy(update={"explanation": self.text(f.explanation, 160), "explanation_ar": self.opt(f.explanation_ar, 160)})
                   for f in t.factors]
        return t.model_copy(update={"factors": factors})

