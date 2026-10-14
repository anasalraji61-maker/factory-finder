from __future__ import annotations

import asyncio
import logging

from .adapters.base import SourceAdapter
from .adapters.registry import AdapterRegistry
from .clients.trust import TrustClient, TrustInfo, unknown
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
        cached = self._results.get(key)
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
        return SearchResponse(
            items=engine.paginate(ranked, page, page_size),
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
        return item

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
