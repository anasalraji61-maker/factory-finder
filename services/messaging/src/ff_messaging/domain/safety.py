"""Content safety: text sanitising, size limits and a bilingual (Arabic / English) abuse filter.

The abuse filter is deliberately simple and predictable:

* terms come from configuration (bundled default list in ``data/abuse_terms.json``);
* text and terms are folded the same way before matching: Unicode NFKD, case folding, removal of
  diacritics (Arabic harakat, Latin accents), tatweel, zero-width and control characters, and
  unification of Arabic letter variants (أ/إ/آ/ٱ → ا, ى → ي, ة → ه, Persian ک/ی → ك/ي);
* every letter of a term may be stretched (``stuuupid``, ``غبيييي``);
* matches are whole words: Latin terms accept common English suffixes, Arabic terms accept the
  common proclitics (و ف ب ك ل ال) and enclitic / plural suffixes;
* by default a matching message is **flagged** (stored and delivered with ``flags``), never
  silently dropped. ``mask`` and ``reject`` are available for stricter deployments.

Known limits (documented, acceptable for wave 1): no Arabizi (``7mar``), no spaced-out letters
(``f u c k``), no semantic understanding.
"""

import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from importlib import resources
from urllib.parse import urlsplit

from ff_messaging.domain.errors import InvalidInputError
from ff_messaging.domain.models import (
    FLAG_ABUSIVE_LANGUAGE,
    AbuseAction,
    Attachment,
    MessageDraft,
    MessageType,
)

# --------------------------------------------------------------------------------------------
# Folding (shared by terms and text)
# --------------------------------------------------------------------------------------------

_TATWEEL = "ـ"
_DROPPED_CATEGORIES = frozenset({"Mn", "Me", "Cf", "Cc", "Cs", "Co", "Cn"})
_ARABIC_FOLD = str.maketrans(
    {
        "ى": "ي",
        "ة": "ه",
        "ٱ": "ا",
        "ک": "ك",
        "ی": "ي",
        "ھ": "ه",
        "ۀ": "ه",
        "ہ": "ه",
    }
)


def _fold_char(ch: str) -> str:
    """Matching form of one character; ``""`` when it carries no letter information."""
    if ch.isspace():
        return " "
    if ch == _TATWEEL or unicodedata.category(ch) in _DROPPED_CATEGORIES:
        return ""
    decomposed = unicodedata.normalize("NFKD", ch)
    kept = "".join(c for c in decomposed if unicodedata.category(c) not in _DROPPED_CATEGORIES)
    return kept.casefold().translate(_ARABIC_FOLD)


@dataclass(frozen=True, slots=True)
class FoldedText:
    """Folded text plus, for every folded character, the span it came from in the original."""

    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]


def fold_with_spans(text: str) -> FoldedText:
    chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for index, ch in enumerate(text):
        folded = _fold_char(ch)
        if not folded:
            # Dropped marks (diacritics, tatweel, zero-width) belong to the preceding letter.
            if ends:
                ends[-1] = index + 1
            continue
        for out in folded:
            chars.append(out)
            starts.append(index)
            ends.append(index + 1)
    return FoldedText("".join(chars), tuple(starts), tuple(ends))


def fold(text: str) -> str:
    return fold_with_spans(text).text


def _is_arabic_script(text: str) -> bool:
    return any(
        "؀" <= c <= "ۿ" or "ݐ" <= c <= "ݿ" or "ࢠ" <= c <= "ࣿ"
        for c in text
    )


def _collapse_runs(word: str) -> str:
    out: list[str] = []
    for ch in word:
        if not out or out[-1] != ch:
            out.append(ch)
    return "".join(out)


def _term_pattern(term: str) -> str | None:
    words = fold(term).split()
    if not words:
        return None
    # Each letter may repeat ("stuuupid", "asssshole"); words may be separated by any non-word run.
    return r"[\W_]+".join(
        "".join(re.escape(ch) + "+" for ch in _collapse_runs(word)) for word in words
    )


_LATIN_SUFFIX = r"(?:s|es|ed|er|ers|ing|in|y)?"
_ARABIC_PREFIX = r"(?:[وف]?(?:[بك]?ال|لل|[بكل])?)"
_ARABIC_SUFFIX = r"(?:ه|ها|هم|هن|ك|كم|كن|ي|نا|ين|ون|ات|ان|ا)?"


def _alternation(patterns: Iterable[str]) -> str:
    return "|".join(sorted(patterns, key=len, reverse=True))


class AbuseFilter:
    """Finds abusive words/phrases and reports their spans in the *original* text."""

    def __init__(self, terms: Iterable[str]) -> None:
        latin: set[str] = set()
        arabic: set[str] = set()
        for term in terms:
            pattern = _term_pattern(term)
            if pattern is None:
                continue
            (arabic if _is_arabic_script(fold(term)) else latin).add(pattern)
        self._regexes: list[re.Pattern[str]] = []
        if latin:
            self._regexes.append(
                re.compile(rf"(?<!\w)(?:{_alternation(latin)}){_LATIN_SUFFIX}(?!\w)")
            )
        if arabic:
            self._regexes.append(
                re.compile(
                    rf"(?<!\w){_ARABIC_PREFIX}(?:{_alternation(arabic)}){_ARABIC_SUFFIX}(?!\w)"
                )
            )
        self.term_count = len(latin) + len(arabic)

    @property
    def enabled(self) -> bool:
        return bool(self._regexes)

    def find(self, text: str) -> list[tuple[int, int]]:
        """Merged ``(start, end)`` spans of abusive terms in ``text`` (original indices)."""
        if not self._regexes or not text:
            return []
        folded = fold_with_spans(text)
        spans: list[tuple[int, int]] = []
        for regex in self._regexes:
            for match in regex.finditer(folded.text):
                if match.end() > match.start():
                    spans.append((folded.starts[match.start()], folded.ends[match.end() - 1]))
        return _merge_spans(spans)

    def contains_abuse(self, text: str) -> bool:
        return bool(self.find(text))


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def mask_spans(text: str, spans: Sequence[tuple[int, int]], mask_char: str = "*") -> str:
    chars = list(text)
    for start, end in spans:
        for index in range(start, end):
            if not chars[index].isspace():
                chars[index] = mask_char
    return "".join(chars)


def load_default_abuse_terms() -> list[str]:
    """Bundled bilingual default list (``ff_messaging/data/abuse_terms.json``)."""
    raw = resources.files("ff_messaging").joinpath("data/abuse_terms.json").read_text("utf-8")
    data = json.loads(raw)
    return [term for terms in data.get("terms", {}).values() for term in terms]


# --------------------------------------------------------------------------------------------
# Text sanitising
# --------------------------------------------------------------------------------------------

_LINE_SEPARATORS = str.maketrans({"\r": "\n", " ": "\n", " ": "\n", "\x85": "\n"})
# Characters that render as nothing but are not whitespace / format characters.
_INVISIBLE_FILLERS = frozenset({"ᅟ", "ᅠ", "⠀", "ㅤ", "ﾠ"})
_NON_VISIBLE_CATEGORIES = frozenset({"Cf", "Mn", "Me", "Cc", "Cs", "Co", "Cn"})


def sanitize_text(value: str) -> str:
    """Normalise newlines, drop control characters (NUL breaks Postgres), NFC, trim."""
    text = value.replace("\r\n", "\n").translate(_LINE_SEPARATORS)
    text = "".join(
        ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cs")
    )
    return unicodedata.normalize("NFC", text).strip()


def has_visible_content(text: str) -> bool:
    return any(
        not ch.isspace()
        and ch not in _INVISIBLE_FILLERS
        and unicodedata.category(ch) not in _NON_VISIBLE_CATEGORIES
        for ch in text
    )


def sanitize_single_line(value: str) -> str:
    return " ".join(sanitize_text(value).split())


# --------------------------------------------------------------------------------------------
# Attachments
# --------------------------------------------------------------------------------------------

_MIME_RE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")


@dataclass(frozen=True, slots=True)
class AttachmentRules:
    max_bytes: int
    allowed_mime_types: tuple[str, ...]
    allow_http: bool = False
    allowed_hosts: tuple[str, ...] = ()
    max_url_length: int = 2048


def _mime_allowed(mime: str, allowed: Sequence[str]) -> bool:
    for pattern in allowed:
        rule = pattern.strip().lower()
        if rule.endswith("*"):
            if mime.startswith(rule[:-1]):
                return True
        elif mime == rule:
            return True
    return False


def _host_allowed(host: str, allowed: Sequence[str]) -> bool:
    for entry in allowed:
        rule = entry.strip().lower().removeprefix("*").removeprefix(".")
        if rule and (host == rule or host.endswith("." + rule)):
            return True
    return False


def _clean_filename(name: str | None) -> str | None:
    if name is None:
        return None
    base = re.split(r"[\\/]", name)[-1]
    cleaned = sanitize_single_line(base)[:255].strip()
    return cleaned or None


def check_attachment(attachment: Attachment, rules: AttachmentRules) -> Attachment:
    url = attachment.url.strip()
    schemes = {"https", "http"} if rules.allow_http else {"https"}
    if attachment.size < 1:
        raise InvalidInputError("Attachment size must be positive", code="invalid_attachment")
    url_error = InvalidInputError(
        "Attachment URL is not allowed",
        code="attachment_url_not_allowed",
        details={"allowed_schemes": sorted(schemes)},
    )
    if not url or len(url) > rules.max_url_length:
        raise url_error
    if any(ch.isspace() or unicodedata.category(ch) == "Cc" for ch in url):
        raise url_error
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".")
        has_credentials = parts.username is not None or parts.password is not None
    except ValueError as exc:
        raise url_error from exc
    if parts.scheme.lower() not in schemes or not host or has_credentials:
        raise url_error
    if rules.allowed_hosts and not _host_allowed(host.lower(), rules.allowed_hosts):
        raise url_error

    mime = attachment.mime.split(";", 1)[0].strip().lower()
    if not _MIME_RE.fullmatch(mime) or not _mime_allowed(mime, rules.allowed_mime_types):
        raise InvalidInputError(
            "Attachment type is not allowed",
            code="attachment_type_not_allowed",
            details={"mime": mime[:127]},
        )
    if attachment.size > rules.max_bytes:
        raise InvalidInputError(
            "Attachment is too large",
            code="attachment_too_large",
            details={"max_bytes": rules.max_bytes, "size": attachment.size},
        )
    return Attachment(url=url, mime=mime, size=attachment.size, name=_clean_filename(attachment.name))


# --------------------------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CheckedMessage:
    draft: MessageDraft  # sanitised (and masked when abuse_action=mask)
    flags: tuple[str, ...]
    abuse_matches: int
    preview_text: str | None  # text for conversation-list previews (always masked when flagged)


class ContentPolicy:
    """Validates user content before it is stored. Pure: no I/O, no clock."""

    def __init__(
        self,
        *,
        max_text_length: int,
        max_title_length: int,
        abuse_filter: AbuseFilter,
        abuse_action: AbuseAction,
        attachment_rules: AttachmentRules,
    ) -> None:
        self.max_text_length = max_text_length
        self.max_title_length = max_title_length
        self.abuse_filter = abuse_filter
        self.abuse_action = abuse_action
        self.attachment_rules = attachment_rules

    def check_message(self, draft: MessageDraft) -> CheckedMessage:
        text = sanitize_text(draft.text) if draft.text is not None else None
        if text is not None and not has_visible_content(text):
            text = None
        attachment = draft.attachment

        if draft.type is MessageType.TEXT:
            if draft.attachment is not None or draft.offer_ref is not None:
                raise InvalidInputError(
                    "Text messages cannot carry an attachment or an offer reference",
                    code="invalid_message",
                )
            if text is None:
                raise InvalidInputError("Message text must not be empty", code="empty_message")
        elif draft.type is MessageType.ATTACHMENT:
            if draft.attachment is None or draft.offer_ref is not None:
                raise InvalidInputError(
                    "Attachment messages need exactly one attachment", code="invalid_message"
                )
            attachment = check_attachment(draft.attachment, self.attachment_rules)
        elif draft.type is MessageType.OFFER_REF:
            if draft.offer_ref is None or draft.attachment is not None:
                raise InvalidInputError(
                    "Offer messages need exactly one offer reference", code="invalid_message"
                )
        else:
            raise InvalidInputError(
                "This message type cannot be sent by users", code="invalid_message_type"
            )

        flags: tuple[str, ...] = ()
        matches = 0
        preview = text
        if text is not None:
            self._check_length(text)
            spans = self.abuse_filter.find(text)
            matches = len(spans)
            if spans:
                if self.abuse_action is AbuseAction.REJECT:
                    raise InvalidInputError(
                        "Message rejected by the content policy",
                        code="message_rejected",
                        details={"reason": FLAG_ABUSIVE_LANGUAGE},
                    )
                flags = (FLAG_ABUSIVE_LANGUAGE,)
                preview = mask_spans(text, spans)
                if self.abuse_action is AbuseAction.MASK:
                    text = preview
        cleaned = replace(draft, text=text, attachment=attachment)
        return CheckedMessage(draft=cleaned, flags=flags, abuse_matches=matches, preview_text=preview)

    def check_title(self, title: str | None) -> str | None:
        if title is None:
            return None
        cleaned = sanitize_single_line(title)
        if not cleaned or not has_visible_content(cleaned):
            return None
        if len(cleaned) > self.max_title_length:
            raise InvalidInputError(
                "Title is too long",
                code="title_too_long",
                details={"max_length": self.max_title_length, "length": len(cleaned)},
            )
        if self.abuse_filter.contains_abuse(cleaned):
            raise InvalidInputError(
                "Title rejected by the content policy",
                code="title_rejected",
                details={"reason": FLAG_ABUSIVE_LANGUAGE},
            )
        return cleaned

    def check_system_text(self, text: str) -> str:
        """System messages come from trusted services: sanitise and bound, never filter."""
        cleaned = sanitize_text(text)
        if not has_visible_content(cleaned):
            raise InvalidInputError("System message text must not be empty", code="empty_message")
        self._check_length(cleaned)
        return cleaned

    def _check_length(self, text: str) -> None:
        if len(text) > self.max_text_length:
            raise InvalidInputError(
                "Message text is too long",
                code="text_too_long",
                details={"max_length": self.max_text_length, "length": len(text)},
            )
