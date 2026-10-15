from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from .adapters.base import SourceAdapter
from .adapters.registry import AdapterRegistry
from .api.errors import ApiError
from .clients.trust import TrustClient, TrustInfo, unknown
from .domain import reco
from .domain import search as engine
from .domain.cache import LRUTTLCache, TTLCache
from .domain.models import (
    Facets,
    Listing,
    ListingDetail,
    SearchQuery,
    SearchResponse,
    SourceStatus,
    Supplier,
)
from .domain.pricehistory import Obs
from .domain.text import english_keywords, extract_quantity, parse_query, query_phrase

log = logging.getLogger(__name__)


class SourcingService:
    def __init__(
        self,
        registry: AdapterRegistry,
        trust: TrustClient,
        adapter_timeout_s: float = 3.0,
        cache_ttl_s: float = 60.0,
        trust_cache_ttl_s: float = 300.0,
        reco_cache_ttl_s: float = 60.0,
        reco_response_ttl_s: float = 30.0,
        reco_cache_max: int = 256,
        provider_concurrency: int = 6,
        reco_budget_s: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.registry = registry
        self.trust = trust
        self.timeout = adapter_timeout_s
        self._results = TTLCache(cache_ttl_s)
        self._trust_cache = TTLCache(trust_cache_ttl_s, maxsize=4096)
        # similar / recommendations: anonymous endpoints, so everything below is keyed by public inputs only
        self._pools = LRUTTLCache(reco_cache_ttl_s, reco_cache_max, clock)  # (adapter, kind, query shape) -> items
        self._details = LRUTTLCache(reco_cache_ttl_s, reco_cache_max, clock)  # listing id -> detail | None
        self._reco_resp = LRUTTLCache(reco_response_ttl_s, reco_cache_max, clock)
        self._sem = asyncio.Semaphore(max(1, provider_concurrency))
        self.reco_budget_s = reco_budget_s
        self.history = None  # PriceHistoryStore (set by main); None = no observations recorded

    # ---- trust ----------------------------------------------------------
    async def _trust_for(self, supplier_id: str) -> TrustInfo:
        hit = self._trust_cache.get(supplier_id)
        if hit is not None:
            return hit
        try:
            info = await self.trust.get(supplier_id)
        except Exception:
            info = unknown(supplier_id)
        if info.band != "unknown":  # do not cache failures
            self._trust_cache.set(supplier_id, info)
        return info

    async def _enrich(self, listings: list[Listing]) -> None:
        ids = sorted({item.supplier.id for item in listings})
        infos = dict(
            zip(ids, await asyncio.gather(*(self._trust_for(i) for i in ids)), strict=True)
        )
        for item in listings:
            info = infos[item.supplier.id]
            item.supplier = item.supplier.model_copy(
                update={"trust_score": info.score, "trust_band": info.band}
            )

    # ---- search ---------------------------------------------------------
    async def _query_adapter(
        self, adapter: SourceAdapter, query: SearchQuery
    ) -> tuple[SourceStatus, list[Listing]]:
        status, items = await self._query_adapter_raw(adapter, query)
        if status.status == "ok" or adapter.mode == "mock":
            return status, items
        return await self._degrade(adapter, query, status)

    async def _degrade(
        self, adapter: SourceAdapter, query: SearchQuery, failed: SourceStatus
    ) -> tuple[SourceStatus, list[Listing]]:
        """A real source failed: serve mock results (labelled) instead of nothing. Never raises."""
        fb = self.registry.fallback()
        if fb is None or self.registry.is_enabled(fb.id):
            return failed, []
        warning = f"{adapter.id} {failed.status}; showing mock results instead"
        log.warning(warning)
        try:
            items = await asyncio.wait_for(fb.search(query), timeout=self.timeout)
        except Exception:
            return failed.model_copy(update={"warning": warning + " (mock also failed)"}), []
        return failed.model_copy(update={"warning": warning}), items

    async def _query_adapter_raw(
        self, adapter: SourceAdapter, query: SearchQuery
    ) -> tuple[SourceStatus, list[Listing]]:
        key = (adapter.id, query.model_dump_json())
        cached = self._results.get(key) if adapter.cacheable else None
        if cached is not None:
            return SourceStatus(source=adapter.id, status="ok"), cached
        try:
            items = await asyncio.wait_for(adapter.search(query), timeout=self.timeout)
        except TimeoutError:
            log.warning("adapter %s timed out", adapter.id)
            return SourceStatus(source=adapter.id, status="timeout"), []
        except Exception as exc:  # isolate: one bad source never fails the search
            log.warning("adapter %s failed: %s", adapter.id, type(exc).__name__)
            return SourceStatus(source=adapter.id, status="error"), []
        if adapter.cacheable:
            self._results.set(key, items)
        return SourceStatus(source=adapter.id, status="ok"), items

    async def search(
        self,
        query: SearchQuery,
        page: int = 1,
        page_size: int = 20,
        sort: str = "relevance",
    ) -> SearchResponse:
        text_q, qty, _unit = extract_quantity(query.q)  # "1000 قطعة" is an order size, not words to match
        terms = parse_query(text_q)
        phrase = query_phrase(text_q)
        update: dict[str, Any] = {"keywords_en": english_keywords(text_q)}
        if qty is not None:  # a buyer ordering N units can use any listing whose minimum order is <= N
            update["moq_max"] = qty if query.moq_max is None else min(qty, query.moq_max)
        query = query.model_copy(update=update)
        outcomes = await asyncio.gather(
            *(self._query_adapter(a, query) for a in self.registry.enabled())
        )
        candidates: list[tuple[Listing, engine.Match]] = []
        sources: list[SourceStatus] = []
        for status, items in outcomes:
            n = 0
            for item in items:
                if not engine.passes_filters(item, query):
                    continue
                m = engine.match(terms, item, phrase)
                if m is None:
                    continue
                candidates.append((item.model_copy(), m))  # shallow: _enrich only rebinds .supplier
                n += 1
            sources.append(status.model_copy(update={"count": n}))
        candidates = engine.prune_weak(engine.dedupe(candidates))
        await self._enrich([c[0] for c in candidates])
        ranked = engine.rank(candidates, sort)
        page_items = engine.paginate(ranked, page, page_size)
        await self._observe(page_items)
        degraded = [x.source for x in sources if x.status != "ok" or x.warning]
        return SearchResponse(
            items=page_items,
            total=len(ranked),
            page=page,
            page_size=page_size,
            sources=sources,
            facets=Facets(**engine.facets(ranked)),
            warning=(
                f"partial_results: {', '.join(degraded)} failed or timed out; results may be incomplete"
                if degraded
                else None
            ),
        )

    # ---- detail ---------------------------------------------------------
    async def _probe(self, call) -> tuple[Any, int]:
        """Ask every enabled adapter; returns (first hit or None, number of adapters that failed/timed out)."""
        failed = 0

        async def one(a: SourceAdapter):
            nonlocal failed
            try:
                return await asyncio.wait_for(call(a), timeout=self.timeout)
            except Exception:
                failed += 1
                return None

        for res in await asyncio.gather(*(one(a) for a in self.registry.enabled())):
            if res is not None:
                return res, failed
        return None, failed

    async def _first(self, call):
        return (await self._probe(call))[0]

    async def get_listing(self, listing_id: str) -> ListingDetail | None:
        """None = definite absence (every adapter answered 'not found'). Raises 503 upstream_timeout when nothing
        was found and at least one adapter failed/timed out (absence cannot be asserted)."""
        item, failed = await self._probe(lambda a: a.get_listing(listing_id))
        if item is None and failed:
            raise ApiError(
                503, "upstream_timeout", "A listing source failed or timed out; try again", {"failed_sources": failed}
            )
        if item is not None:
            await self._enrich([item])
            await self._observe([item])
        return item

    async def _observe(self, items: list[Listing]) -> None:
        if self.history is not None and items:
            await self.history.record_listings(items)  # best effort, never raises

    async def get_supplier(self, supplier_id: str) -> Supplier | None:
        sup = await self._first(lambda a: a.get_supplier(supplier_id))
        if sup is not None:
            info = await self._trust_for(supplier_id)
            sup = sup.model_copy(update={"trust_score": info.score, "trust_band": info.band})
        return sup

    async def sources_overview(self) -> list[dict]:
        async def one(a: SourceAdapter) -> dict:
            enabled = self.registry.is_enabled(a.id)
            status = "disabled"
            if enabled:
                try:
                    h = await asyncio.wait_for(a.health(), timeout=self.timeout)
                    status = "ok" if h.ok else "error"
                except TimeoutError:
                    status = "timeout"
                except Exception:
                    status = "error"
            return {
                "id": a.id,
                "name": a.name,
                "mode": a.mode,
                "enabled": enabled,
                "configured": a.configured(),
                "status": status,
                "compliance": a.compliance,
            }

        return list(await asyncio.gather(*(one(a) for a in self.registry.all())))

    # ---- price history --------------------------------------------------
    async def stored_prices(self, listing_id: str, since) -> list[Obs]:
        if self.history is None:
            return []
        try:
            return await self.history.series(listing_id, since)
        except Exception as exc:
            log.warning("price history read failed: %s", type(exc).__name__)
            return []

    # ---- similar / recommendations -------------------------------------------
    PARTIAL_WARNING = "partial_results: time budget exceeded, results may be incomplete"

    def invalidate_reco(self) -> None:
        """Drop cached pools/details/responses (called when a live local store changes)."""
        for c in (self._pools, self._details, self._reco_resp):
            c.clear()

    @staticmethod
    async def _gather_until(coros: list[Coroutine[Any, Any, Any]], deadline: float) -> tuple[list[Any], bool]:
        """Run ``coros`` concurrently until ``deadline`` (time.monotonic). Unfinished/failed ones yield ``None``;
        returns (results in input order, whether any was cut off by the budget)."""
        tasks = [asyncio.ensure_future(c) for c in coros]
        if not tasks:
            return [], False
        _, pending = await asyncio.wait(tasks, timeout=max(0.0, deadline - time.monotonic()))
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        out = [None if (t in pending or t.cancelled() or t.exception() is not None) else t.result() for t in tasks]
        return out, bool(pending)

    async def _detail(self, listing_id: str) -> ListingDetail | None:
        """Reference lookup: cached (also negatively) and bounded by the provider semaphore."""
        hit = self._details.get(listing_id)
        if hit is not LRUTTLCache.MISS:
            return hit

        async def call(a: SourceAdapter):
            async with self._sem:
                return await a.get_listing(listing_id)

        item, failed = await self._probe(call)
        if item is not None or not failed:  # definite answers only: a transient failure is never cached
            self._details.set(listing_id, item)
        return item

    async def _pool_part(self, adapter: SourceAdapter, kind: str | None) -> list[ListingDetail]:
        key = (adapter.id, kind, "limit200")  # the query shape is fixed: SearchQuery(kind=kind, limit=200)
        hit = self._pools.get(key)
        if hit is not LRUTTLCache.MISS:
            return hit
        async with self._sem:
            status, items = await self._query_adapter(adapter, SearchQuery(kind=kind, limit=200))  # type: ignore[arg-type]
        if status.status == "ok" and not status.warning:  # never cache failures or degraded (mock-substituted) results
            self._pools.set(key, items)
        return items

    async def _pool(self, kinds: set[str], deadline: float) -> tuple[list[ListingDetail], bool]:
        coros = [self._pool_part(a, k) for k in (sorted(kinds) or [None]) for a in self.registry.enabled()]
        outcomes, cut = await self._gather_until(coros, deadline)
        seen: dict[str, ListingDetail] = {}
        for items in outcomes:
            for it in items or ():
                seen.setdefault(it.id, it)
        return list(seen.values()), cut

    async def _rank_candidates(
        self,
        refs: list[tuple[ListingDetail, float]],
        pool: list[ListingDetail],
        country: str | None,
        limit: int,
        per_supplier: int | None,
        deadline: float | None = None,
    ) -> tuple[list[reco.Recommended], bool]:
        ref_ids = {r.id for r, _ in refs}
        pool = [c for c in pool if c.id not in ref_ids]
        country = country.upper() if country else None

        def score(item: ListingDetail, cf: reco.Features, feats: list[tuple[reco.Features, float, str]]):
            best: tuple[float, list[reco.Reason], str | None] = (0.0, [], None)
            if feats:
                for rf, w, rid in feats:
                    sc, why = reco.similarity(rf, cf, item)
                    if sc * w > best[0]:
                        best = (sc * w, why, rid)
            else:  # no usable reference: trust-led fallback
                band = item.supplier.trust_band
                sc = 0.3 + reco._TRUST_W.get(band, 0.0) + (0.02 if item.supplier.verified else 0.0)
                why = [reco.reason("top_trusted")] if band == "green" else []
                if item.supplier.verified:
                    why.append(reco.reason("verified_supplier"))
                best = (sc, why, None)
            sc, why, rid = best
            if sc <= 0:
                return 0.0, []
            if rid and per_supplier is not None:  # recommendations (not /similar): say which view it follows
                why = [*why, reco.reason("because_viewed", rid)]
            if country and cf.country == country:
                sc += 0.05
                why = [*why, reco.reason("origin_country_match")]
            return max(0.0, min(1.0, sc)), why

        feats = [(reco.features(r), w, r.id) for r, w in refs]
        cats = {f.category for f, _, _ in feats}
        pool = sorted(pool, key=lambda c: (c.category not in cats, not c.supplier.verified, c.id))[: reco.MAX_CANDIDATES]
        cfeat = {c.id: reco.features(c) for c in pool}  # token sets built once per candidate, reused by both scoring passes
        pre = sorted(((score(c, cfeat[c.id], feats)[0], c) for c in pool), key=lambda x: (-x[0], x[1].id))
        stage = [c.model_copy() for sc, c in pre[: reco.TRUST_STAGE] if sc > 0]
        degraded = False
        try:  # trust lookups only for the best pre-scored candidates (cached per supplier)
            left = 30.0 if deadline is None else max(0.25, deadline - time.monotonic())
            await asyncio.wait_for(self._enrich(stage), timeout=left)
        except TimeoutError:
            degraded = True  # score without trust bands rather than fail
        out: list[reco.Recommended] = []
        for c in stage:
            sc, why = score(c, cfeat[c.id], feats)
            if sc >= reco.MIN_SCORE:
                out.append(reco.Recommended(listing=reco.as_listing(c), score=round(sc, 4), reasons=why))
        out.sort(key=reco.rank_key)
        if per_supplier is None:
            return out[:limit], degraded
        kept: list[reco.Recommended] = []
        count: dict[str, int] = {}
        for r in out:
            n = count.get(r.listing.supplier.id, 0)
            if n < per_supplier:
                count[r.listing.supplier.id] = n + 1
                kept.append(r)
        return kept[:limit], degraded

    async def similar(
        self, listing_id: str, limit: int
    ) -> tuple[ListingDetail, list[reco.Recommended], str | None] | None:
        key = ("sim", listing_id, limit)
        hit = self._reco_resp.get(key)
        if hit is not LRUTTLCache.MISS:
            return hit
        deadline = time.monotonic() + self.reco_budget_s
        found, cut = await self._gather_until([self._detail(listing_id)], deadline)
        if found[0] is None:
            if cut:
                raise ApiError(503, "upstream_timeout", "Sources did not answer in time; retry shortly")
            return None
        ref = found[0].model_copy()  # shared cache entry: never mutate it
        await self._enrich([ref])
        await self._observe([ref])
        pool, cut2 = await self._pool({ref.kind}, deadline)
        ranked, degraded = await self._rank_candidates([(ref, 1.0)], pool, None, limit, None, deadline)
        partial = cut or cut2 or degraded
        res = (ref, ranked, self.PARTIAL_WARNING if partial else None)
        if not partial:
            self._reco_resp.set(key, res)
        return res

    async def recommendations(
        self, ref_ids: list[str], country: str | None, limit: int
    ) -> tuple[list[str], list[reco.Recommended], str | None]:
        """``ref_ids`` are recent listing ids, most recent first (weight decays with position)."""
        # Key keeps the caller's order (it sets the recency weights), de-duplicated; sorting it would merge
        # different rankings.
        key = ("rec", tuple(dict.fromkeys(ref_ids)), country.upper() if country else None, limit)
        hit = self._reco_resp.get(key)
        if hit is not LRUTTLCache.MISS:
            return hit
        deadline = time.monotonic() + self.reco_budget_s
        found, cut = await self._gather_until([self._detail(i) for i in key[1]], deadline)
        refs = [(r, max(0.5, 1 - 0.05 * n)) for n, r in enumerate(x for x in found if x is not None)]
        pool, cut2 = await self._pool({r.kind for r, _ in refs}, deadline)
        ranked, degraded = await self._rank_candidates(refs, pool, country, limit, reco.PER_SUPPLIER_CAP, deadline)
        partial = cut or cut2 or degraded
        res = ([r.id for r, _ in refs], ranked, self.PARTIAL_WARNING if partial else None)
        if not partial:
            self._reco_resp.set(key, res)
        return res
