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

from ff_demand import compliance
from ff_demand.config import Settings
from ff_demand.errors import CapReached, Conflict, Forbidden, Invalid, NotFound
from ff_demand.intent import detect_language, extract_intent, signal_key
from ff_demand.publisher import Publisher, guard_publish, text_sha
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
    value = compliance.clean_listing_text(_URL.sub("", value))
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
        publisher: Publisher | None = None,
    ):
        self.store, self.sourcing, self.settings, self.source = store, sourcing, settings, source
        self.publisher = publisher  # None = no adapter at all; never called automatically
        self.clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    # ---- ingestion -------------------------------------------------------------------------
    async def import_signal(self, raw: RawSignal, language: str | None = None) -> dict:
        if raw.scraping_disallowed or raw.source.casefold() in self.settings.blocked_source_set:
            raise Forbidden(
                "Source disallows automated access (robots/ToS); signal not ingested",
                code="source_disallowed",
            )
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
        tkey = compliance.thread_key(raw.url, key)
        akey = compliance.author_key(raw.author)
        keys = [k for k in (tkey, akey) if k]
        if compliance.is_opt_out(raw.text) or await self.store.is_suppressed(keys):
            # the stranger opted out (now or before): suppress forever, keep no text
            if compliance.is_opt_out(raw.text):
                await self._suppress(tkey, akey, "post", None, now)
            sig = {
                "id": f"sig_{uuid.uuid4().hex[:16]}",
                "status": "suppressed",
                "language": lang,
                "text": "[redacted: opt-out]",
                "url": None,
                "source": raw.source,
                "intent": None,
                "created_at": _iso(now),
            }
            await self.store.add_signal(sig, key, now)
            return {"signal": sig, "draft": None, "duplicate": False, "created": True}
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
            listings = [
                {
                    "id": c.id,
                    "title": _clean(c.title_ar if lang == "ar" and c.title_ar else c.title),
                    "supplier_name": _clean(c.supplier_name, 80),
                    "price_min": f"{c.price_min:f}",
                    "price_max": f"{c.price_max:f}",
                    "currency": c.currency,
                }
                for c in candidates
            ]
            draft = {
                "id": f"drf_{uuid.uuid4().hex[:16]}",
                "signal_id": sig["id"],
                "status": "draft",
                "language": lang,
                "text": build_reply(lang, candidates),
                "listing_ids": [c.id for c in candidates],
                "listings": listings,
                "allowed_numbers": compliance.allowed_numbers(listings),
                "thread_key": tkey,
                "author_key": akey,
                "approved_text_sha": None,
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
            out = []
            for r in await self.source.fetch():
                try:
                    out.append(await self.import_signal(r))
                except Forbidden:  # disallowed source: skipped, never ingested
                    continue
            return out
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

    def _validate(self, d: dict, text: str, signal_text: str) -> None:
        compliance.validate_reply(
            text,
            language=d["language"],
            signal_text=signal_text,
            allowed=d.get("allowed_numbers", []),
            blocked_domains=self.settings.blocked_domain_set,
            disclosure=DISCLOSURE[d["language"]],
        )

    async def _signal_text(self, d: dict) -> str:
        sig = await self.store.get_signal(d["signal_id"])
        return (sig or {}).get("text", "")

    async def _suppress(
        self, tkey: str, akey: str | None, reason: str, actor: str | None, now: datetime
    ) -> list[str]:
        added = []
        for key, kind in ((tkey, "thread"), (akey, "author")):
            if key and await self.store.add_suppression(
                key, kind, now, {"key": key, "kind": kind, "reason": reason, "by": actor,
                                 "at": _iso(now)}
            ):  # fmt: skip
                added.append(kind)
        return added

    async def record_opt_out(
        self, actor: str, author: str | None, url: str | None, note: str | None
    ) -> dict:
        """Permanent suppression of a stranger (author hash and/or thread hash). Idempotent; there
        is no way to undo it through this service."""
        compliance.require_human(actor)
        akey = compliance.author_key(author)
        if not akey and not url:
            raise Invalid("author or url is required")
        now = self.clock()
        tkey = compliance.thread_key(url, "") if url else None
        added = []
        for key, kind in ((tkey, "thread"), (akey, "author")):
            if key and await self.store.add_suppression(
                key, kind, now, {"key": key, "kind": kind, "reason": "opt_out", "by": actor,
                                 "note": note, "at": _iso(now)}
            ):  # fmt: skip
                added.append(kind)
        rejected = 0
        for d in await self.store.drafts_by_keys([k for k in (tkey, akey) if k]):
            if d["status"] in ("draft", "approved"):
                prev = d["status"]
                d["status"] = "rejected"
                _audit(d, {"at": _iso(now), "actor": actor, "action": "rejected",
                           "note": "opt_out"})  # fmt: skip
                rejected += await self.store.save_draft(d, prev)
        return {"recorded": added, "rejected_drafts": rejected}

    async def edit(self, did: str, actor: str, text: str) -> dict:
        """Human edit. Any edit voids a previous approval: the draft returns to ``draft`` and has to
        be approved again (and counts against the cap/cooldown again only then)."""
        compliance.require_human(actor)
        d = await self.get_draft(did)
        prev = d["status"]
        if prev not in ("draft", "approved"):
            raise Conflict(f"Cannot edit a {prev} draft")
        text = text.strip()
        if len(text) < 5:
            raise Invalid("Edited text is too short")
        d["text"] = ensure_disclosure(text, d["language"])
        self._validate(d, d["text"], await self._signal_text(d))
        now = self.clock()
        d.update(status="draft", approved_by=None, approved_at=None, approved_text_sha=None)
        _audit(
            d,
            {"at": _iso(now), "actor": actor, "action": "edited",
             "note": "approval reset" if prev == "approved" else None},
        )  # fmt: skip
        if not await self.store.reset_approval(d, prev):
            raise Conflict("Draft changed concurrently")
        return d

    async def approve(self, did: str, actor: str, text: str | None) -> dict:
        compliance.require_human(actor)
        self._require_enabled()
        d = await self.get_draft(did)
        if d["status"] != "draft":
            raise Conflict(f"Cannot approve a {d['status']} draft")
        if text is not None:
            if len(text.strip()) < 5:
                raise Invalid("Edited text is too short")
            d["text"] = ensure_disclosure(text.strip(), d["language"])
        self._validate(d, d["text"], await self._signal_text(d))
        now = self.clock()
        d.update(
            status="approved",
            approved_by=actor,
            approved_at=_iso(now),
            approved_text_sha=text_sha(d["text"]),
        )
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
        res = await self.store.approve_draft(
            d,
            now,
            cap=self.settings.daily_cap,
            day_start=start,
            day_end=end,
            cooldown_since=now - timedelta(hours=self.settings.thread_cooldown_hours),
        )
        if res == "ok":
            return d
        fresh = await self.get_draft(did)
        if fresh["status"] != "draft":
            raise Conflict(f"Cannot approve a {fresh['status']} draft")
        if res == "opted_out":
            fresh["status"] = "rejected"
            _audit(fresh, {"at": _iso(now), "actor": "system", "action": "rejected",
                           "note": "opt_out"})  # fmt: skip
            await self.store.save_draft(fresh, "draft")
            raise Forbidden("The author or thread opted out of contact", code="opted_out")
        if res == "cooldown":
            raise CapReached(
                "A reply to this thread/author was approved recently",
                details={"cooldown_hours": self.settings.thread_cooldown_hours},
                code="thread_cooldown",
            )
        raise CapReached(
            "Daily approval cap reached", details={"daily_cap": self.settings.daily_cap}
        )

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

    async def publish_via_adapter(self, did: str, actor: str) -> dict:
        """Optional adapter path. Not exposed over HTTP, never invoked by poll/import; needs a
        named human, the kill-switch on, an adapter, and an approved unedited draft."""
        compliance.require_human(actor)
        self._require_enabled()
        if self.publisher is None:
            raise Forbidden("No publisher adapter configured", code="publisher_disabled")
        d = await self.get_draft(did)
        guard_publish(d, actor)
        url = await self.publisher.publish(d, actor)
        return await self.mark_published(did, actor, url)

    async def mark_published(self, did: str, actor: str, url: str | None) -> dict:
        compliance.require_human(actor)
        self._require_enabled()
        d = await self.get_draft(did)
        if d["status"] != "approved":
            raise Conflict("Only an approved draft can be marked published")
        guard_publish(d, actor)
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
