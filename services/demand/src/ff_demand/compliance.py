"""Compliance rules for outgoing draft text and strangers' opt-outs (CLAUDE.md rules 6-7).

Pure functions, no I/O. A human still approves every reply; these checks make sure a human cannot
(by accident) approve text that leaks contact data, impersonates a person, invents prices, echoes
injected text from the source post or links to blocked domains.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from urllib.parse import urlsplit

from ff_demand.errors import Invalid

DEFAULT_BLOCKED_DOMAINS = (
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "cutt.ly", "wa.me", "t.me",
    "api.whatsapp.com", "chat.whatsapp.com", "telegram.me", "m.me",
)  # fmt: skip
AUTOMATED_ACTORS = ("system", "bot", "auto", "service", "cron", "worker", "anonymous", "unknown")

_LINK = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s<>\"')\]]+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|cn|me|ly|co|info|biz|ru|app|link|xyz)\b[^\s]*"
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_TLDS = r"(?:com|net|org|io|cn|me|co|info|biz|ru|app|xyz|edu|gov|iq|ae|sa|tr|de|uk)"
_AT = r"(?:\s*[\[({<]\s*(?:at|@)\s*[\])}>]\s*|\s+at\s+|\s*@\s*)"
_DOT = r"(?:\s*[\[({<]\s*(?:dot|\.)\s*[\])}>]\s*|\s+dot\s+|\s*\.\s*)"
_EMAIL_OBF = re.compile(
    rf"(?i)(?<![\w.+-])[\w.+-]+{_AT}[\w-]+(?:{_DOT}[\w-]+)*?{_DOT}{_TLDS}\b"
)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]{4}){2,7}(?:[ -]?[A-Z0-9]{1,3})?\b")
_HANDLE = re.compile(r"(?<![\w])@[A-Za-z0-9_.]{3,}")
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d\s().-]{7,}\d")
_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

_HUMAN_CLAIMS = re.compile(
    r"(?i)(\bi am (a |an )?(person|human|individual|private|real person)\b"
    r"|\bi'?m (a |an )?(person|human|individual|real person)\b"
    r"|\bmy name is\b|\bas a (private )?(buyer|customer|individual)\b"
    r"|\bnot a (bot|company|platform)\b"
    r"|أنا شخص|انا شخص|اسمي\b|أنا إنسان|انا انسان|لست (منصة|شركة|بوت)|مو منصة|مو شركة)"
)
_INJECTION = re.compile(
    r"(?i)(ignore (all |any |the )?(previous|prior|above) (instructions?|prompts?)"
    r"|disregard (all |the )?(previous|prior|above)|system prompt|you are now\b|act as\b"
    r"|developer mode|jailbreak|<\s*/?\s*(system|assistant|script)\b|\[\s*inst\s*\]"
    r"|تجاهل (كل |جميع )?(التعليمات|الأوامر)|تعليمات النظام|انسَ|انس التعليمات)"
)
_CLAIMS = re.compile(
    r"(?i)(guarantee[ds]?|lowest price|cheapest|free shipping|money[- ]back|certified by|"
    r"ضمان|مضمون|أرخص|ارخص|شحن مجاني|استرجاع)"
)
_OPT_OUT = re.compile(
    r"(?i)(do not|don'?t|stop|never) (contact|message|dm|email|text|call|reach out)(?: to)? me"
    r"|stop (messaging|contacting|dm'?ing) me|no (dms|solicitation|spam|offers)\b"
    r"|leave me alone|opt[- ]?out|unsubscribe|not interested,? (please )?(stop|don'?t)"
    r"|(لا|ما|مو) (تتواصل|تراسل|تكلم|تتصل|تبعث|ترسل)\w*( لي| معي| علي| عليّ)?"
    r"|لا اريد (اي )?(رسائل|تواصل|عروض)|لا أريد (أي )?(رسائل|تواصل|عروض)"
    r"|اتركوني|بدون (رسائل|تواصل|عروض)|لا ترسل"
)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def thread_key(url: str | None, fallback: str) -> str:
    """Stable key for a post/thread: scheme/host/path only (query & fragment dropped)."""
    if url:
        p = urlsplit(url.strip())
        return sha("t:" + f"{p.hostname or ''}{p.path.rstrip('/')}".casefold())
    return sha("t:" + fallback)


def author_key(author: str | None) -> str | None:
    a = (author or "").strip().lstrip("@").casefold()
    return sha("a:" + a) if a else None


_RANGE = re.compile(r"\d+(?:\.\d+)?\s?-\s?\d+(?:\.\d+)?")


def _phones(text: str) -> list[str]:
    """Phone-like runs; plain price ranges such as ``3500-4200`` are not phone numbers."""
    out = []
    for m in _PHONE.findall(text.translate(_ARABIC_DIGITS)):
        m = m.strip()
        if not _RANGE.fullmatch(m) and len(re.sub(r"\D", "", m)) >= 8:
            out.append(m)
    return out


def is_opt_out(text: str) -> bool:
    return bool(_OPT_OUT.search(text))


def is_automated_actor(actor: str | None) -> bool:
    a = (actor or "").strip().casefold()
    return not a or any(
        a == w or a.startswith((w + ":", w + "-", w + "_")) for w in AUTOMATED_ACTORS
    )


def require_human(actor: str | None) -> None:
    if is_automated_actor(actor):
        raise Invalid("A named human administrator is required", details={"actor": actor or ""})


def _host(link: str) -> str:
    link = link if "//" in link else "//" + link
    return (urlsplit(link).hostname or "").casefold().rstrip(".")


def blocked_link(text: str, blocked: Iterable[str]) -> str | None:
    bl = {b.casefold().lstrip(".") for b in blocked}
    for m in _LINK.finditer(text):
        h = _host(m.group(0))
        if any(h == b or h.endswith("." + b) for b in bl):
            return h
    return None


def numbers_in(text: str) -> set[str]:
    out = set()
    for n in _NUM.findall(text.translate(_ARABIC_DIGITS)):
        out.add(n.replace(",", ""))
    return out


def allowed_numbers(listings: list[dict]) -> list[str]:
    """Numbers a draft may mention: prices and digits found in the matched listings."""
    out: set[str] = set()
    for item in listings:
        for k in ("price_min", "price_max", "title", "supplier_name"):
            out |= numbers_in(str(item.get(k, "")))
    return sorted(out)


def _norm_num(n: str) -> str:
    return n.rstrip("0").rstrip(".") if "." in n else n


def clean_listing_text(value: str) -> str:
    """Strip links, e-mails, @handles and phone numbers from supplier-controlled text."""
    for rx in (_LINK, _EMAIL, _HANDLE):
        value = rx.sub("", value)
    for ph in _phones(value):
        value = value.replace(ph, "")
    return value


def validate_reply(
    text: str,
    *,
    language: str,
    signal_text: str,
    allowed: list[str],
    blocked_domains: Iterable[str],
    disclosure: str,
) -> None:
    """Raise Invalid(code=...) when a draft must not be approved/kept."""

    def bad(reason: str) -> None:
        raise Invalid(f"Reply rejected: {reason}", code=reason)

    if disclosure not in text:
        bad("missing_disclosure")
    body = text.replace(disclosure, "")
    if _EMAIL.search(body) or _HANDLE.search(body) or _phones(body):
        bad("contact_data")
    bdigits = re.sub(r"\D", "", body.translate(_ARABIC_DIGITS))
    for m in _EMAIL.findall(signal_text) + _HANDLE.findall(signal_text):
        if m.strip().casefold() in body.casefold():
            bad("contact_data")
    for m in _phones(signal_text):  # the stranger's own number, however it is formatted
        if re.sub(r"\D", "", m) in bdigits:
            bad("contact_data")
    if blocked_link(body, blocked_domains):
        bad("blocked_domain")
    if _HUMAN_CLAIMS.search(body):
        bad("claims_human")
    if _INJECTION.search(body):
        bad("injection")
    sig = re.sub(r"\s+", " ", signal_text).strip().casefold()
    flat = re.sub(r"\s+", " ", body).casefold()
    if len(sig) >= 40 and any(sig[i : i + 40] in flat for i in range(len(sig) - 39)):
        bad("echoes_source_post")
    if _CLAIMS.search(body):
        bad("unlisted_price_or_claim")
    ok = {_norm_num(n) for n in allowed}
    if {_norm_num(n) for n in numbers_in(body)} - ok:
        bad("unlisted_price_or_claim")
    ar_chars = len(re.findall(r"[؀-ۿ]", body))
    lat_chars = len(re.findall(r"[A-Za-z]", body))
    if (language == "ar" and (ar_chars == 0 or ar_chars < lat_chars * 0.5)) or (
        language == "en" and lat_chars <= ar_chars
    ):
        bad("wrong_language")


def scrub_pii(text: str) -> str:
    """Replace e-mails, phone numbers, @handles and links with placeholders before storage."""
    text = _EMAIL_OBF.sub("[email]", text)
    text = _EMAIL.sub("[email]", text)
    text = _IBAN.sub(
        lambda m: "[iban]" if sum(c.isdigit() for c in m.group()) >= 6 else m.group(), text
    )
    text = _LINK.sub("[link]", text)
    text = _HANDLE.sub("[handle]", text)
    for ph in sorted(_phones(text), key=len, reverse=True):
        text = text.replace(ph, "[phone]")
    # Arabic-Indic digit phone runs: _phones() works on translated text, so retry on that view
    tr = text.translate(_ARABIC_DIGITS)
    if tr != text:
        for ph in _phones(tr):
            tr = tr.replace(ph, "[phone]")
        text = tr
    return text


def link_count(text: str) -> int:
    return len(_LINK.findall(text))
