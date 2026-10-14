"""Optional, provider-agnostic LLM layer (OFF by default; the rules parser stays the source of truth).

Two narrow uses, both strictly validated and both falling back to the deterministic path on any
error, timeout or invalid output:

* ``extract_query``: intent/entity extraction when the rule parser has low confidence. The reply
  must be a JSON object; only whitelisted fields survive and the merged result is re-validated
  into ``ParsedQuery``.
* ``rewrite_answer``: optional tone rewrite. Every number in the rewrite must match the original
  answer's numbers exactly (same multiset), otherwise the original text is returned. The LLM can
  therefore never introduce or alter a price, total, score or id.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from ff_assistant.config import Settings
from ff_assistant.domain.query import Intent, ParsedQuery


class LlmError(Exception):
    """Any LLM failure (transport, timeout, bad status, malformed envelope)."""


class LlmClient(Protocol):
    async def complete(self, system: str, user: str, max_tokens: int) -> str: ...


class MockLlm:
    """Deterministic: returns ``reply`` (a string, or a callable of (system, user)); default ``{}``."""

    def __init__(self, reply: str | Callable[[str, str], str] = "{}") -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        self.calls.append((system, user))
        return self.reply(system, user) if callable(self.reply) else self.reply


class HttpLlm:
    """Anthropic Messages API shape over httpx. The key is never logged or put in errors."""

    def __init__(self, s: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if s.llm_api_key is None:
            raise LlmError("no API key configured")
        self._key = s.llm_api_key.get_secret_value()
        self._model = s.llm_model
        self._url = s.llm_base_url.rstrip("/") + "/v1/messages"
        self._http = httpx.AsyncClient(timeout=s.llm_timeout_s, transport=transport)

    def __repr__(self) -> str:
        return f"HttpLlm(model={self._model!r}, url={self._url!r})"

    async def complete(self, system: str, user: str, max_tokens: int) -> str:
        body = {"model": self._model, "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        try:
            r = await self._http.post(self._url, json=body, headers=headers)
            r.raise_for_status()
            blocks = r.json()["content"]
            return "".join(b["text"] for b in blocks if b.get("type") == "text")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise LlmError(type(exc).__name__) from None  # never echo request details

    async def aclose(self) -> None:
        await self._http.aclose()


def build_llm(s: Settings) -> LlmClient | None:
    if s.llm == "mock":
        return MockLlm()
    if s.llm == "anthropic" and s.llm_api_key is not None:
        return HttpLlm(s)
    return None


# -- (a) extraction ----------------------------------------------------------------------------
_EXTRACT_SYSTEM = (
    "You extract a sourcing query from a buyer message (Arabic or English). Reply with ONE JSON object only, "
    'with optional keys: "intent" (search|quote|help), "kind" (product|raw_material|production_line), '
    '"condition" (new|used|refurbished), "keywords" (array of short strings), "query" (short product phrase), '
    '"category" (string). Use only what the message states. No prose.'
)
_PATCH_KEYS = {"intent", "kind", "condition", "keywords", "query", "category"}
_ALLOWED_INTENTS = {Intent.SEARCH, Intent.QUOTE, Intent.HELP}


def _json_object(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group())
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


async def extract_query(llm: LlmClient, s: Settings, text: str, parsed: ParsedQuery) -> ParsedQuery:
    """Merge a validated LLM patch into ``parsed``; return ``parsed`` unchanged on any problem."""
    try:
        raw = await llm.complete(_EXTRACT_SYSTEM, text[: s.llm_max_input_chars], s.llm_max_tokens)
    except Exception:  # noqa: BLE001 - the LLM is strictly optional
        return parsed
    patch = _json_object(raw)
    if not patch:
        return parsed
    patch = {k: v for k, v in patch.items() if k in _PATCH_KEYS and v}
    try:
        if "intent" in patch:
            patch["intent"] = Intent(patch["intent"])
            if patch["intent"] not in _ALLOWED_INTENTS:
                del patch["intent"]
        for k in ("query", "category"):
            if k in patch and not (isinstance(patch[k], str) and len(patch[k]) <= 120):
                raise ValueError(k)
        if "keywords" in patch:
            kw = patch["keywords"]
            if not (isinstance(kw, list) and len(kw) <= 10 and all(isinstance(x, str) and 0 < len(x) <= 60 for x in kw)):
                raise ValueError("keywords")
        merged = ParsedQuery.model_validate({**parsed.model_dump(), **patch})
    except (ValueError, ValidationError):
        return parsed
    return merged


# -- (b) rewrite -------------------------------------------------------------------------------
_REWRITE_SYSTEM = (
    "Rewrite the assistant answer for a friendlier, clearer tone. Keep the SAME language and keep every "
    "number, currency, id and name exactly as written. Do not add, remove or change any figure or fact. "
    "Keep the line structure. Reply with the rewritten text only."
)
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def numbers_in(text: str) -> Counter[str]:
    return Counter(n.replace(",", "") for n in _NUM_RE.findall(text.translate(_DIGITS)))


async def rewrite_answer(llm: LlmClient, s: Settings, answer: str) -> str:
    """Tone rewrite, accepted only if all numbers match the original exactly and length is sane."""
    try:
        out = (await llm.complete(_REWRITE_SYSTEM, answer[: s.llm_max_input_chars], s.llm_max_tokens)).strip()
    except Exception:  # noqa: BLE001
        return answer
    if not out or len(out) > 2 * len(answer) + 80 or numbers_in(out) != numbers_in(answer):
        return answer
    return out
