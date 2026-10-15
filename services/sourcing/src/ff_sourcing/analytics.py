"""Privacy-safe supplier analytics for native listings.

Only daily aggregate counters per listing and metric are persisted (table ``listing_stats_daily``): no IP, user id,
user agent or any per-viewer row ever reaches the database or the logs. Viewer identity exists only transiently, in
bounded in-memory structures, as a truncated HMAC keyed by a secret *and the UTC day*, so the same viewer hashes
differently every day and nothing survives a restart or the day change.

Counting rules
- ``impression``: a native listing appeared on a served search page (server side, raw count).
- ``view`` / ``contact_click`` / ``share``: client events; the same viewer (user id when signed in, else client IP)
  counts at most once per ``dedupe_s`` per listing+type. The daily ``uniques`` estimate counts distinct viewers in a
  size-capped set; when a cap is hit the estimate saturates (undercounts) instead of growing memory.
- ``report``: a new (non-duplicate) user report. ``watchlist_add``: internal hook ``Analytics.bump`` (not exposed).
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import logging
import secrets
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from .api.errors import ApiError
from .db import Base, ListingStatRow

log = logging.getLogger(__name__)

EVENT_TYPES = ("view", "contact_click", "share")
METRICS = ("impression", "view", "contact_click", "share", "watchlist_add", "report")
MAX_IMPRESSIONS_PER_CALL = 100
TOP_LISTINGS = 20


def pct_change(cur: int, prev: int) -> float | None:
    return None if prev == 0 else round((cur - prev) * 100 / prev, 1)


def rate(num: int, den: int) -> float | None:
    return None if den == 0 else round(min(1.0, num / den), 4)


class Analytics:
    def __init__(
        self,
        engine: AsyncEngine,
        auto_create: bool = True,
        *,
        hash_key: str = "",
        dedupe_s: float = 1800.0,
        rate_per_min: int = 60,
        unique_cap: int = 2000,
        max_sets: int = 20000,
        dedupe_max: int = 50000,
        limiter_max: int = 50000,
        retention_days: int = 400,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.engine = engine
        self.sm = async_sessionmaker(engine, expire_on_commit=False)
        self._auto_create = auto_create
        self._ready = False
        self._key = (hash_key or secrets.token_hex(16)).encode()
        self.dedupe_s = dedupe_s
        self.rate_per_min = rate_per_min
        self.unique_cap = unique_cap
        self.max_sets = max_sets
        self.dedupe_max = dedupe_max
        self.limiter_max = limiter_max
        self.retention_days = retention_days
        self._clock = clock or (lambda: datetime.now(UTC))
        self._mono = monotonic
        # transient, bounded, wiped on UTC day change
        self._day: date | None = None
        self._seen: OrderedDict[tuple[int, str, str], float] = OrderedDict()
        self._sets: dict[tuple[str, str], set[int]] = {}
        self._limits: OrderedDict[int, deque[float]] = OrderedDict()
        self._last_purge: float | None = None

    async def ensure_ready(self) -> None:
        if self._ready or not self._auto_create:
            return
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self._ready = True

    # ---- transient state -----------------------------------------------------
    def _today(self) -> date:
        day = self._clock().astimezone(UTC).date()
        if day != self._day:  # salt rotation: yesterday's hashes can never match today's
            self._day = day
            self._seen.clear()
            self._sets.clear()
            self._limits.clear()
        return day

    def _hash(self, day: date, who: str) -> int:
        k = self._key + b"|" + day.isoformat().encode()
        return int.from_bytes(hmac.new(k, who.encode(), hashlib.sha256).digest()[:8], "big")

    def _rate_check(self, h: int) -> None:
        now = self._mono()
        q = self._limits.get(h)
        if q is None:
            if len(self._limits) >= self.limiter_max:
                self._limits.popitem(last=False)  # bounded: drop the least recently used viewer
            q = self._limits[h] = deque()
        else:
            self._limits.move_to_end(h)
        while q and now - q[0] >= 60:
            q.popleft()
        if len(q) >= self.rate_per_min:
            retry = int(60 - (now - q[0])) + 1
            raise ApiError(429, "rate_limited", "Too many events", {"retry_after_s": retry})
        q.append(now)

    def _first_in_window(self, h: int, listing_id: str, etype: str) -> bool:
        now = self._mono()
        key = (h, listing_id, etype)
        last = self._seen.get(key)
        if last is not None and now - last < self.dedupe_s:
            return False
        self._seen[key] = now
        self._seen.move_to_end(key)
        while len(self._seen) > self.dedupe_max:
            self._seen.popitem(last=False)
        return True

    def _new_unique(self, h: int, listing_id: str, etype: str) -> bool:
        s = self._sets.get((listing_id, etype))
        if s is None:
            if len(self._sets) >= self.max_sets:
                return False  # saturated: estimate undercounts rather than growing memory
            s = self._sets[(listing_id, etype)] = set()
        if h in s:
            return False
        if len(s) >= self.unique_cap:
            return False
        s.add(h)
        return True

    # ---- recording -------------------------------------------------------------
    async def record_event(self, listing_id: str, etype: str, ip: str, user_id: str | None, countable: bool) -> bool:
        """Client event. Rate limits (per IP and per user) apply to every attempt; returns whether it was counted."""
        day = self._today()
        self._rate_check(self._hash(day, "ip:" + ip))
        who = "u:" + user_id if user_id else "ip:" + ip
        h = self._hash(day, who)
        if user_id:
            self._rate_check(h)
        if not countable or not self._first_in_window(h, listing_id, etype):
            return False
        uniq = 1 if self._new_unique(h, listing_id, etype) else 0
        await self.bump(listing_id, etype, 1, uniq)
        return True

    async def impressions(self, listing_ids: list[str]) -> None:
        ids = list(dict.fromkeys(i for i in listing_ids if i.startswith("nat_")))[:MAX_IMPRESSIONS_PER_CALL]
        if not ids:
            return
        try:
            await self.bump_many([(i, "impression", 1, 0) for i in ids])
        except Exception as exc:  # analytics never breaks search
            log.warning("impression count failed: %s", type(exc).__name__)

    async def bump(self, listing_id: str, metric: str, n: int = 1, uniq: int = 0) -> None:
        """Internal hook (e.g. ``bump(id, "watchlist_add")`` from the notifications flow); best effort."""
        try:
            await self.bump_many([(listing_id, metric, n, uniq)])
        except Exception as exc:
            log.warning("analytics write failed: %s", type(exc).__name__)

    async def bump_many(self, items: list[tuple[str, str, int, int]]) -> None:
        await self.ensure_ready()
        day = self._today()
        async with self.sm() as s:
            for lid, metric, n, uniq in items:
                await self._upsert(s, lid, day, metric, n, uniq)
            await s.commit()
        await self._maybe_purge()

    @staticmethod
    async def _upsert(s, lid: str, day: date, metric: str, n: int, uniq: int) -> None:
        pk = (ListingStatRow.listing_id == lid, ListingStatRow.day == day, ListingStatRow.metric == metric)
        vals = {"count": ListingStatRow.count + n, "uniques": ListingStatRow.uniques + uniq}
        if (await s.execute(update(ListingStatRow).where(*pk).values(**vals))).rowcount:
            return
        try:
            async with s.begin_nested():
                s.add(ListingStatRow(listing_id=lid, day=day, metric=metric, count=n, uniques=uniq))
        except IntegrityError:  # concurrent first write
            await s.execute(update(ListingStatRow).where(*pk).values(**vals))

    # ---- retention / erasure ------------------------------------------------------
    async def purge(self, now: datetime | None = None) -> int:
        await self.ensure_ready()
        cutoff = (now or self._clock()).astimezone(UTC).date() - timedelta(days=self.retention_days)
        async with self.sm() as s:
            res = await s.execute(delete(ListingStatRow).where(ListingStatRow.day < cutoff))
            await s.commit()
        return int(res.rowcount or 0)

    async def _maybe_purge(self) -> None:
        now = self._mono()
        if self._last_purge is not None and now - self._last_purge < 3600:
            return
        self._last_purge = now
        with contextlib.suppress(Exception):
            await self.purge()

    # ---- reading -------------------------------------------------------------------
    async def overview(self, listings: list[tuple[str, str, str]], days: int) -> dict:
        """``listings`` = [(id, title, status)] the caller owns. Periods end today (UTC, inclusive)."""
        await self.ensure_ready()
        today = self._today()
        cur_from = today - timedelta(days=days - 1)
        prev_from = cur_from - timedelta(days=days)
        ids = [x[0] for x in listings]
        daily: dict[date, dict[str, int]] = {}
        per_listing: dict[str, dict[str, int]] = {}
        uniq_cur: dict[str, int] = {}
        prev: dict[str, int] = {}
        cur: dict[str, int] = {}
        if ids:
            async with self.sm() as s:
                q = (
                    select(ListingStatRow.day, ListingStatRow.metric, func.sum(ListingStatRow.count), func.sum(ListingStatRow.uniques))
                    .where(ListingStatRow.listing_id.in_(ids), ListingStatRow.day >= prev_from, ListingStatRow.day <= today)
                    .group_by(ListingStatRow.day, ListingStatRow.metric)
                )
                for day, metric, c, u in (await s.execute(q)).all():
                    if day >= cur_from:
                        daily.setdefault(day, {})[metric] = int(c)
                        cur[metric] = cur.get(metric, 0) + int(c)
                        uniq_cur[metric] = uniq_cur.get(metric, 0) + int(u)
                    else:
                        prev[metric] = prev.get(metric, 0) + int(c)
                q2 = (
                    select(ListingStatRow.listing_id, ListingStatRow.metric, func.sum(ListingStatRow.count))
                    .where(ListingStatRow.listing_id.in_(ids), ListingStatRow.day >= cur_from, ListingStatRow.day <= today)
                    .group_by(ListingStatRow.listing_id, ListingStatRow.metric)
                )
                for lid, metric, c in (await s.execute(q2)).all():
                    per_listing.setdefault(lid, {})[metric] = int(c)
        totals = {m: cur.get(m, 0) for m in METRICS}
        previous = {m: prev.get(m, 0) for m in METRICS}
        series = []
        for i in range(days):
            d = cur_from + timedelta(days=i)
            row = daily.get(d, {})
            series.append({"date": d.isoformat(), **{m: row.get(m, 0) for m in METRICS}})
        meta = {lid: (title, status) for lid, title, status in listings}
        table = []
        for lid, m in per_listing.items():
            table.append(
                {
                    "listing_id": lid,
                    "title": meta[lid][0],
                    "status": meta[lid][1],
                    **{k: m.get(k, 0) for k in METRICS},
                    "view_to_contact": rate(m.get("contact_click", 0), m.get("view", 0)),
                }
            )
        table.sort(key=lambda r: (-r["view"], -r["impression"], -r["contact_click"], r["listing_id"]))
        return {
            "period": {
                "days": days,
                "from": cur_from.isoformat(),
                "to": today.isoformat(),
                "previous_from": prev_from.isoformat(),
                "previous_to": (cur_from - timedelta(days=1)).isoformat(),
            },
            "totals": totals,
            "unique_viewers": {
                "view": uniq_cur.get("view", 0),
                "contact_click": uniq_cur.get("contact_click", 0),
                "note": "sum of per-day estimates; the same person on two days counts twice",
            },
            "previous_totals": previous,
            "change_pct": {m: pct_change(totals[m], previous[m]) for m in METRICS},
            "conversion": {
                "view_to_contact": rate(totals["contact_click"], totals["view"]),
                "impression_to_view": rate(totals["view"], totals["impression"]),
                "previous_view_to_contact": rate(previous["contact_click"], previous["view"]),
            },
            "series": series,
            "listings": table[:TOP_LISTINGS],
            "listings_total": len(table),
        }
