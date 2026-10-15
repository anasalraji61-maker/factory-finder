"""Demand pipeline + human-in-the-loop state machine.

Status machine:  draft -> approved -> published
                 draft -> rejected,  approved -> rejected
Nothing is ever posted by this service; `published` only records that a human did it.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ff_demand.config import Settings
from ff_demand.errors import CapReached, Conflict, Forbidden, Invalid, NotFound
from ff_demand.intent import detect_language, extract_intent, signal_key
from ff_demand.signals import RawSignal, SignalSource
from ff_demand.sourcing import Candidate, SourcingClient, SourcingUnavailableError
from ff_demand.store import Store

DISCLOSURE = {
    "ar": "ملاحظة: هذا الرد من منصة مُوَرِّد (Factory Finder) للتوريد، وليس من شخص عادي.",
    "en": "Note: this reply is from the Factory Finder sourcing platform, not an individual.",
}
OUTCOMES = ("replied", "converted", "no_response")
MAX_AUDIT = 50  # per-draft audit cap: repeatable calls cannot grow the document forever


def _iso(dt: datetime) -> str:
    return dt.isoformat()


_URL = re.compile(r"(?i)(https?://|www\.)\S+")
_WS = re.compile(r"\s+")


def _clean(value: str, limit: int = 120) -> str:
    """Supplier-controlled listing text: strip links, control chars and line breaks."""
    value = _URL.sub("", value)
    value = "".join(ch for ch in value if ch.isprintable() or ch.isspace())
    return _WS.sub(" ", value).strip()[:limit]


def _audit(d: dict, entry: dict) -> None:
    """Append an audit entry; past the cap the oldest entries after the first are dropped."""
    d["audit"].append(entry)
    if len(d["audit"]) > MAX_AUDIT:
        d["audit"] = [d["audit"][0], *d["audit"][-(MAX_AUDIT - 1) :]]


def ensure_disclosure(text: str, language: str) -> str:
    """Every reply must carry the platform disclosure, even after a human edit."""
    note = DISCLOSURE[language]
    return text if note in text else f"{text.rstrip()}\n{note}"


def build_reply(language: str, candidates: list[Candidate]) -> str:
    """Honest, listing-data-only reply. No price promises: figures are indicative."""
    ar = language == "ar"
    lines = []
    for c in candidates:
        title = _clean(c.title_ar if ar and c.title_ar else c.title)
        supplier = _clean(c.supplier_name, 80)
        rng = (
            f"{c.price_min:f}" if c.price_min == c.price_max else f"{c.price_min:f}-{c.price_max:f}"
        )
        if ar:
            lines.append(f"- {title} ({supplier}): {rng} {c.currency} حسب بيانات الإعلان")
        else:
            lines.append(f"- {title} ({supplier}): {rng} {c.currency} per the listing")
    if ar:
        head = "هلا بيك، لقينا بالمنصة خيارات تطابق طلبك:"
        tail = (
            "الأسعار تقريبية حسب بيانات الموردين وقابلة للتغيير، وتكلفة الشحن والجمارك تُحسب "
            "بشكل منفصل. إذا تحب نرتب لك التفاصيل، كلمنا على المنشور."
        )
    else:
        head = "Hi, we found options on our platform that match your request:"
        tail = (
            "Prices are indicative, taken from supplier listings, and may change; shipping and "
            "duties are calculated separately. Reply here if you want the details."
        )
    return "\n".join([head, *lines, tail, DISCLOSURE[language]])


class DemandService:
    def __init__(
        self,
        store: Store,
        sourcing: SourcingClient,
        settings: Settings,
        source: SignalSource | None = None,
    ):
        self.store, self.sourcing, self.settings, self.source = store, sourcing, settings, source
        self.clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    # ---- ingestion -------------------------------------------------------------------------
    async def import_signal(self, raw: RawSignal, language: str | None = None) -> dict:
        key = signal_key(raw.text, raw.url)
        existing = await self.store.signal_by_key(key)
        if existing:
            return {
                "signal": existing,
                "draft": await self.store.draft_for_signal(existing["id"]),
                "duplicate": True,
                "created": False,
            }
        now = self.clock()
        lang = detect_language(raw.text, language)
        intent = extract_intent(raw.text)
        sig = {
            "id": f"sig_{uuid.uuid4().hex[:16]}",
            "status": "ignored",
            "language": lang,
            "text": raw.text,
            "url": raw.url,
            "source": raw.source,
            "intent": None,
            "created_at": _iso(now),
        }
        candidates: list[Candidate] = []
        if intent:
            sig["intent"] = {"query": intent.query, "origin_country": intent.origin_country}
            try:
                candidates = await self.sourcing.search(
                    intent.query, intent.origin_country, self.settings.max_candidates
                )
            except SourcingUnavailableError:
                candidates = []
            sig["status"] = "drafted" if candidates else "no_match"
        await self.store.add_signal(sig, key, now)
        draft = None
        if candidates:
            draft = {
                "id": f"drf_{uuid.uuid4().hex[:16]}",
                "signal_id": sig["id"],
                "status": "draft",
                "language": lang,
                "text": build_reply(lang, candidates),
                "listing_ids": [c.id for c in candidates],
                "disclosure": True,
                "approved_by": None,
                "approved_at": None,
                "published_url": None,
                "outcome": None,
                "audit": [{"at": _iso(now), "actor": "system", "action": "drafted", "note": None}],
                "created_at": _iso(now),
            }
            await self.store.add_draft(draft, now)
        return {"signal": sig, "draft": draft, "duplicate": False, "created": True}

    async def poll(self) -> list[dict]:
        try:
            if self.source is None:
                return []
            return [await self.import_signal(r) for r in await self.source.fetch()]
        finally:
            await self.prune()

    async def prune(self) -> dict[str, int]:
        c, now = self.settings, self.clock()
        sig = now - timedelta(days=c.signal_retention_days) if c.signal_retention_days else None
        rdays = c.rejected_draft_retention_days
        rej = now - timedelta(days=rdays) if rdays else None
        if sig is None and rej is None:
            return {"signals": 0, "drafts": 0}
        return await self.store.purge(sig, rej)

    # ---- drafts ----------------------------------------------------------------------------
    async def get_draft(self, did: str) -> dict:
        d = await self.store.get_draft(did)
        if not d:
            raise NotFound("Draft not found")
        return d

    def _require_enabled(self) -> None:
        if not self.settings.enabled:
            raise Forbidden(
                "Demand publishing is disabled (FF_DEMAND_ENABLED=false)", code="kill_switch"
            )

    def _day(self) -> tuple[datetime, datetime]:
        now = self.clock().astimezone(UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)

    async def quota(self) -> dict:
        used = await self.store.count_approved(*self._day())
        cap = self.settings.daily_cap
        return {
            "enabled": self.settings.enabled,
            "daily_cap": cap,
            "used_today": used,
            "remaining": max(cap - used, 0),
        }

    async def approve(self, did: str, actor: str, text: str | None) -> dict:
        self._require_enabled()
        d = await self.get_draft(did)
        if d["status"] != "draft":
            raise Conflict(f"Cannot approve a {d['status']} draft")
        if text is not None:
            if len(text.strip()) < 5:
                raise Invalid("Edited text is too short")
            d["text"] = ensure_disclosure(text.strip(), d["language"])
        now = self.clock()
        d.update(status="approved", approved_by=actor, approved_at=_iso(now))
        _audit(
            d,
            {
                "at": _iso(now),
                "actor": actor,
                "action": "approved",
                "note": "text edited" if text is not None else None,
            },
        )
        start, end = self._day()
        ok = await self.store.save_draft(
            d, "draft", now, cap=self.settings.daily_cap, day_start=start, day_end=end
        )
        if not ok:
            fresh = await self.get_draft(did)
            if fresh["status"] != "draft":
                raise Conflict(f"Cannot approve a {fresh['status']} draft")
            raise CapReached(
                "Daily approval cap reached", details={"daily_cap": self.settings.daily_cap}
            )
        return d

    async def reject(self, did: str, actor: str, reason: str | None) -> dict:
        d = await self.get_draft(did)
        prev = d["status"]
        if prev not in ("draft", "approved"):
            raise Conflict(f"Cannot reject a {prev} draft")
        d["status"] = "rejected"
        _audit(d, {"at": _iso(self.clock()), "actor": actor, "action": "rejected", "note": reason})
        if not await self.store.save_draft(d, prev):
            raise Conflict("Draft changed concurrently")
        return d

    async def mark_published(self, did: str, actor: str, url: str | None) -> dict:
        self._require_enabled()
        d = await self.get_draft(did)
        if d["status"] != "approved":
            raise Conflict("Only an approved draft can be marked published")
        d["status"] = "published"
        d["published_url"] = url
        _audit(d, {"at": _iso(self.clock()), "actor": actor, "action": "published", "note": url})
        if not await self.store.save_draft(d, "approved"):
            raise Conflict("Draft changed concurrently")
        return d

    async def outcome(self, did: str, actor: str, outcome: str, note: str | None) -> dict:
        if outcome not in OUTCOMES:
            raise Invalid("Unknown outcome", details={"allowed": list(OUTCOMES)})
        d = await self.get_draft(did)
        if d["status"] != "published":
            raise Conflict("Outcome can only be recorded for published drafts")
        d["outcome"] = outcome
        _audit(
            d,
            {
                "at": _iso(self.clock()),
                "actor": actor,
                "action": f"outcome:{outcome}",
                "note": note,
            },
        )
        if not await self.store.save_draft(d, "published"):
            raise Conflict("Draft changed concurrently")
        return d
