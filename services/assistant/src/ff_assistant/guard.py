"""Prompt-injection guardrails: third-party text (listing titles, supplier names, carrier events,
HS descriptions, trust notes) is DATA. It is cleaned of control/bidi characters, markup and
instruction-like phrases, length-capped, and only ever interpolated into answers and cards. It is
never placed in an LLM system prompt, never parsed for intents, and never used to pick a tool,
a user id or a downstream URL.
"""

from __future__ import annotations

import re
import unicodedata

from ff_assistant.domain.models import Listing, TrustScore

FILTERED = "[filtered]"
WARNING = "untrusted_text_filtered"
INJECTION_WARNING = "prompt_injection_ignored"

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
    r"|\bjailbreak\b|\bdeveloper\s+mode\b|\bdo\s+anything\s+now\b"
    r"|(?:كلي|قلي|اعطني|اعطيني|ورجيني)\s+(?:ال)?(?:توكن|مفتاح|باسورد|كلمة\s+السر)"
    # Turkish / Persian / Kurdish (Sorani) / Chinese
    r"|(?:önceki|onceki|tüm|tum)\s+(?:talimatlar\w*|kurallar\w*)\s*(?:yoksay|unut)|sistem\s+(?:istemi|komutu)\w*\s+(?:göster|goster|söyle|soyle)|api\s+anahtar\w*\s+(?:göster|goster|ver|söyle)"
    r"|(?:دستورات|دستورالعمل(?:‌|\s)?های|قوانین)\s+(?:قبلی|پیشین)\s*(?:را)?\s*(?:نادیده|فراموش)|(?:کلید|توکن)\s+(?:api|ای\s*پی\s*آی|سیستم)?\s*(?:را)?\s*(?:نشان\s+بده|بگو|بفرست)"
    r"|(?:ڕێنماییەکانی|ڕێنمایی|ڕێساکانی)\s+(?:پێشوو|پێشتر)\s*(?:فەرامۆش|پشتگوێ)|(?:کلیلی|توکنی)\s*(?:api|سیستەم)?\s*(?:پیشان\s+بدە|پێم\s+بڵێ)"
    r"|忽略\s*(?:之前|以上|所有|先前)?\s*的?\s*(?:指令|指示|规则|提示)|系统\s*提示|(?:告诉我|显示|给我)\s*(?:你的)?\s*(?:api\s*)?(?:密钥|令牌|token)"
)


_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}")
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff\u00ad\u0640\u064b-\u065f]")


def is_injection(text: str | None) -> bool:
    """True when *user* text tries to override instructions or extract secrets (strict; checked before parsing)."""
    if not text:
        return False
    t = unicodedata.normalize("NFKC", str(text))
    return any(_INJECT.search(v) for v in (_INVISIBLE.sub("", t), _CTRL.sub(" ", _INVISIBLE.sub(" ", t))))


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

    def ident(self, value: str | None) -> str:
        """Identifiers from downstream (listing / supplier / deal ids, HS codes) must look like ids; anything else is dropped."""
        if value and _IDENT.fullmatch(value):
            return value
        self.hit = self.hit or bool(value)
        return "invalid-id"

    def url(self, value: str | None) -> str | None:
        """Only plain http(s) URLs without whitespace/control characters are passed on to the client."""
        if value and re.fullmatch(r"https?://[^\s<>\"'`\\]{1,500}", value) and not _CTRL.search(value):
            return value
        self.hit = self.hit or bool(value)
        return None

    def loc(self, loc):
        if loc is None or not loc.city:
            return loc
        return loc.model_copy(update={"city": self.text(loc.city, 60)})

    def listing(self, lst: Listing) -> Listing:
        sup = lst.supplier.model_copy(update={"id": self.ident(lst.supplier.id), "name": self.text(lst.supplier.name, 80),
                                              "location": self.loc(lst.supplier.location)})
        extras = {k: self.text(v, 300) for k, v in (lst.model_extra or {}).items() if isinstance(v, str) and k != "source_url"}
        update = {"id": self.ident(lst.id), "source": self.text(lst.source, 40), "unit": self.opt(lst.unit, 30),
                  "hs_code": self.ident(lst.hs_code) if lst.hs_code else None, "origin": self.loc(lst.origin),
                  "source_url": self.url(lst.source_url),
                  "images": [u for u in (self.url(i) for i in lst.images) if u] if lst.images is not None else None,
                  "title": self.text(lst.title, 160), "title_ar": self.opt(lst.title_ar, 160), "supplier": sup,
                  "category": self.opt(lst.category, 60), **extras}
        return lst.model_copy(update=update)

    def trust(self, t: TrustScore) -> TrustScore:
        factors = [f.model_copy(update={"key": self.text(f.key, 40), "explanation": self.text(f.explanation, 160), "explanation_ar": self.opt(f.explanation_ar, 160)})
                   for f in t.factors]
        return t.model_copy(update={"supplier_id": self.ident(t.supplier_id), "factors": factors})

