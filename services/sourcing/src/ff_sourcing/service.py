from __future__ import annotations

import asyncio
import logging

from .adapters.base import SourceAdapter
from .adapters.registry import AdapterRegistry
from .clients.trust import TrustClient, TrustInfo, unknown
from .domain import reco
from .domain import search as engine
from .domain.cache import TTLCache
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
from .domain.text import english_keywords, parse_query, query_phrase

log = logging.getLogger(__name__)


class SourcingService:
    def __init__(
        self,
        registry: AdapterRegistry,
        trust: TrustClient,
        adapter_timeout_s: float = 3.0,
        cache_ttl_s: float = 60.0,
        trust_cache_ttl_s: float = 300.0,
    ):
        self.registry = registry
        self.trust = trust
        self.timeout = adapter_timeout_s
        self._results = TTLCache(cache_ttl_s)
        self._trust_cache = TTLCache(trust_cache_ttl_s, maxsize=4096)
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
        terms = parse_query(query.q)
        phrase = query_phrase(query.q)
        query = query.model_copy(update={"keywords_en": english_keywords(query.q)})
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
        candidates = engine.dedupe(candidates)
        await self._enrich([c[0] for c in candidates])
        ranked = engine.rank(candidates, sort)
        page_items = engine.paginate(ranked, page, page_size)
        await self._observe(page_items)
        return SearchResponse(
            items=page_items,
            total=len(ranked),
            page=page,
            page_size=page_size,
            sources=sources,
            facets=Facets(**engine.facets(ranked)),
        )

    # ---- detail ---------------------------------------------------------
    async def _first(self, call):
        async def one(a: SourceAdapter):
            try:
                return await asyncio.wait_for(call(a), timeout=self.timeout)
            except Exception:
                return None

        for res in await asyncio.gather(*(one(a) for a in self.registry.enabled())):
            if res is not None:
                return res
        return None

    async def get_listing(self, listing_id: str) -> ListingDetail | None:
        item = await self._first(lambda a: a.get_listing(listing_id))
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
    async def _pool(self, kinds: set[str]) -> list[ListingDetail]:
        queries = [SearchQuery(kind=k, limit=200) for k in (sorted(kinds) or [None])]  # type: ignore[arg-type]
        outcomes = await asyncio.gather(
            *(self._query_adapter(a, q) for q in queries for a in self.registry.enabled())
        )
        seen: dict[str, ListingDetail] = {}
        for _, items in outcomes:
            for it in items:
                seen.setdefault(it.id, it)
        return list(seen.values())

    async def _rank_candidates(
        self,
        refs: list[tuple[ListingDetail, float]],
        pool: list[ListingDetail],
        country: str | None,
        limit: int,
        per_supplier: int | None,
    ) -> list[reco.Recommended]:
        ref_ids = {r.id for r, _ in refs}
        pool = [c for c in pool if c.id not in ref_ids]
        country = country.upper() if country else None

        def score(item: ListingDetail, feats: list[tuple[reco.Features, float, str]]):
            cf = reco.features(item)
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
        pre = sorted(((score(c, feats)[0], c) for c in pool), key=lambda x: (-x[0], x[1].id))
        stage = [c.model_copy() for sc, c in pre[: reco.TRUST_STAGE] if sc > 0]
        await self._enrich(stage)  # trust lookups only for the best pre-scored candidates (cached per supplier)
        out: list[reco.Recommended] = []
        for c in stage:
            sc, why = score(c, feats)
            if sc >= reco.MIN_SCORE:
                out.append(reco.Recommended(listing=reco.as_listing(c), score=round(sc, 4), reasons=why))
        out.sort(key=reco.rank_key)
        if per_supplier is None:
            return out[:limit]
        kept: list[reco.Recommended] = []
        count: dict[str, int] = {}
        for r in out:
            n = count.get(r.listing.supplier.id, 0)
            if n < per_supplier:
                count[r.listing.supplier.id] = n + 1
                kept.append(r)
        return kept[:limit]

    async def similar(self, listing_id: str, limit: int) -> tuple[ListingDetail, list[reco.Recommended]] | None:
        ref = await self.get_listing(listing_id)
        if ref is None:
            return None
        pool = await self._pool({ref.kind})
        return ref, await self._rank_candidates([(ref, 1.0)], pool, None, limit, None)

    async def recommendations(
        self, ref_ids: list[str], country: str | None, limit: int
    ) -> tuple[list[str], list[reco.Recommended]]:
        """``ref_ids`` are recent listing ids, most recent first (weight decays with position)."""
        async def one(i: str):
            try:
                return await self._first(lambda a: a.get_listing(i))
            except Exception:
                return None

        found = await asyncio.gather(*(one(i) for i in ref_ids))
        refs = [(r, max(0.5, 1 - 0.05 * n)) for n, r in enumerate(x for x in found if x is not None)]
        pool = await self._pool({r.kind for r, _ in refs})
        ranked = await self._rank_candidates(refs, pool, country, limit, reco.PER_SUPPLIER_CAP)
        return [r.id for r, _ in refs], ranked
