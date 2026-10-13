"""Orchestration: parsed intent -> downstream calls -> typed result, degrading gracefully."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from ff_assistant import compose
from ff_assistant.clients.base import ClientError, Clients
from ff_assistant.config import Settings
from ff_assistant.domain.gazetteer import Gazetteer
from ff_assistant.domain.models import (
    LandedCostQuote,
    Listing,
    Location,
    TrustScore,
    band_for_score,
)
from ff_assistant.domain.parser import parse
from ff_assistant.domain.query import Intent, ParsedQuery
from ff_assistant.llm import LlmRefiner

SERVICE_AR = {"sourcing": "البحث", "logistics": "حساب الشحن", "trust": "فحص الموثوقية", "tracking": "التتبع"}


class AssistantResult(BaseModel):
    intent: Intent
    parsed_query: ParsedQuery
    answer_text: str
    listings: list[Listing] = Field(default_factory=list)
    quote: LandedCostQuote | None = None
    trust: TrustScore | None = None
    warnings: list[str] = Field(default_factory=list)


class Assistant:
    def __init__(self, clients: Clients, settings: Settings, gaz: Gazetteer | None = None, llm: LlmRefiner | None = None) -> None:
        self.c, self.s = clients, settings
        self.gaz = gaz or Gazetteer.default()
        self.llm = llm

    async def handle(self, text: str, destination: Location | None = None) -> AssistantResult:
        p = parse(text, self.gaz, destination)
        if self.llm is not None and p.confidence < self.s.llm_min_confidence:
            p = await self._refine(text, p)
        warnings: list[str] = []
        handler = {Intent.SEARCH: self._search, Intent.QUOTE: self._quote, Intent.TRUST: self._trust,
                   Intent.TRACK: self._track, Intent.HELP: self._help}[p.intent]
        res = await handler(p, warnings)
        res.warnings = warnings
        if warnings:
            res.answer_text += "\n" + " ".join(f"ملاحظة: خدمة {SERVICE_AR.get(w.split('_')[0], w)} غير متاحة حالياً."
                                             for w in warnings if w.endswith("_unavailable"))
            res.answer_text = res.answer_text.strip()
        return res

    async def _refine(self, text: str, p: ParsedQuery) -> ParsedQuery:
        try:
            patch = await self.llm.refine(text, p)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - the LLM is strictly optional
            return p
        if not patch:
            return p
        data = p.model_dump()
        data.update({k: v for k, v in patch.items() if k in {"kind", "condition", "keywords", "query", "category"} and v})
        return ParsedQuery.model_validate(data)

    async def _guard(self, service: str, coro: Any, warnings: list[str]) -> Any:
        try:
            return await coro
        except ClientError:
            warnings.append(f"{service}_unavailable")
            return None

    # -- intents ---------------------------------------------------------------------------
    async def _search_listings(self, p: ParsedQuery, warnings: list[str], size: int | None = None):
        params: dict[str, Any] = {
            "q": p.query or None, "kind": p.kind.value if p.kind else None,
            "condition": p.condition.value if p.condition else None,
            "origin_country": p.origin.country_code if p.origin else None,
            "page_size": size or self.s.search_page_size,
        }
        if p.budget and p.budget.currency == "USD":
            params["max_price" if p.budget.bound == "max" else "min_price"] = str(p.budget.amount)
        elif p.budget:
            warnings.append("budget_currency_ignored")
        return await self._guard("sourcing", self.c.sourcing.search(params), warnings)

    async def _search(self, p: ParsedQuery, warnings: list[str]) -> AssistantResult:
        res = await self._search_listings(p, warnings)
        listings = res.items[: self.s.max_listings] if res else []
        quote = trust = None
        if listings:
            top = listings[0]
            trust = await self._supplier_trust(top, warnings)
            if p.destination:
                quote = await self._quote_for(p, top, warnings)
        text = compose.search_text(p, listings, res.total if res else 0, self.gaz) if res else \
            "ما كدرت أجيب نتائج بحث هسه، جرّب بعد شوي."
        if quote:
            text += "\n" + compose.quote_text(quote, self.gaz)
        elif listings and not p.destination:
            text += "\n" + compose.need_destination()
        if trust and listings:
            text += "\n" + compose.trust_text(trust)
        return AssistantResult(intent=p.intent, parsed_query=p, answer_text=text, listings=listings, quote=quote, trust=trust)

    async def _supplier_trust(self, listing: Listing, warnings: list[str]) -> TrustScore | None:
        sup = listing.supplier
        score = await self._guard("trust", self.c.trust.supplier_score(sup.id), warnings)
        if score is None and sup.trust_score is not None:
            score = TrustScore(supplier_id=sup.id, score=sup.trust_score, band=sup.trust_band or band_for_score(sup.trust_score), factors=[])
        return score

    async def _quote_for(self, p: ParsedQuery, listing: Listing | None, warnings: list[str]) -> LandedCostQuote | None:
        if p.destination is None:
            return None
        origin = p.origin or (listing.origin or listing.supplier.location if listing else None)
        goods = self._goods(p, listing)
        if origin is None or goods is None:
            warnings.append("quote_insufficient_data")
            return None
        req = {"goods": goods, "origin": origin.model_dump(exclude_none=True),
               "destination": p.destination.model_dump(exclude_none=True),
               "display_currency": self.s.default_currency}
        return await self._guard("logistics", self.c.logistics.landed_cost(req), warnings)

    def _goods(self, p: ParsedQuery, lst: Listing | None) -> dict[str, Any] | None:
        from ff_assistant.domain.lexicon import UNITS

        qty = p.quantity or (Decimal(lst.moq) if lst and lst.moq else Decimal(1))
        kg_per = {u: k for u, k in {v[0]: v[1] for v in UNITS.values()}.items() if k}
        weight = None
        if p.unit in kg_per:
            weight = qty * kg_per[p.unit]
        elif lst and lst.unit_weight_kg:
            weight = qty * Decimal(str(lst.unit_weight_kg))
        if weight is None or lst is None:
            return None
        per_unit = (lst.price.min.amount + lst.price.max.amount) / 2
        units = weight / Decimal(str(lst.unit_weight_kg)) if lst.unit_weight_kg else qty
        value = (units * per_unit).quantize(Decimal("0.01"))
        return {"description": lst.title, "quantity": str(qty), "unit": p.unit or lst.unit,
                "total_value": {"amount": str(value), "currency": lst.price.min.currency},
                "total_weight_kg": str(weight.quantize(Decimal("0.01"))), "category": lst.category}

    async def _quote(self, p: ParsedQuery, warnings: list[str]) -> AssistantResult:
        if p.destination is None:
            return AssistantResult(intent=p.intent, parsed_query=p, answer_text=compose.need_destination())
        res = await self._search_listings(p.model_copy(update={"budget": None}), warnings, size=3)
        top = res.items[0] if res and res.items else None
        quote = await self._quote_for(p, top, warnings) if top else None
        if quote:
            text = compose.quote_text(quote, self.gaz)
        elif top is None and "sourcing_unavailable" not in warnings:
            text = "ما لقيت منتج مطابق أبني عليه سعر الشحن. اذكر السعر أو اسم المنتج بشكل أوضح."
        else:
            text = "ما كدرت أحسب الكلفة الكاملة هسه."
        return AssistantResult(intent=p.intent, parsed_query=p, answer_text=text,
                               listings=[top] if top else [], quote=quote)

    async def _trust(self, p: ParsedQuery, warnings: list[str]) -> AssistantResult:
        if not p.supplier_id:
            return AssistantResult(intent=p.intent, parsed_query=p, answer_text="اكتب رقم المورد (مثل sup_cn_001) حتى أفحص موثوقيته.")
        score = await self._guard("trust", self.c.trust.supplier_score(p.supplier_id), warnings)
        text = compose.trust_text(score) if score else f"تعذّر فحص المورد {p.supplier_id} الآن."
        return AssistantResult(intent=p.intent, parsed_query=p, answer_text=text, trust=score)

    async def _track(self, p: ParsedQuery, warnings: list[str]) -> AssistantResult:
        if not p.reference or not p.reference_type:
            return AssistantResult(intent=p.intent, parsed_query=p, answer_text="اكتب رقم الحاوية أو بوليصة الشحن الجوي أو رقم IMO للسفينة حتى أتحقق منه.")
        check = await self._guard("tracking", self.c.tracking.validate(p.reference_type, p.reference), warnings)
        kind = {"container": "الحاوية", "awb": "بوليصة الشحن الجوي", "vessel_imo": "السفينة"}[p.reference_type]
        if check is None:
            text = f"استلمت رقم {kind} {p.reference} لكن خدمة التتبع غير متاحة للتحقق منه الآن."
        elif check.valid:
            text = f"رقم {kind} {p.reference} صحيح. أضفه من تبويب الشحنات لمتابعة حالته ومواعيد الوصول."
        else:
            text = f"رقم {kind} {p.reference} غير صحيح ({check.reason or 'فشل التحقق'}). تأكد من الرقم وأعد الكتابة."
        return AssistantResult(intent=p.intent, parsed_query=p, answer_text=text)

    async def _help(self, p: ParsedQuery, warnings: list[str]) -> AssistantResult:
        return AssistantResult(intent=p.intent, parsed_query=p, answer_text=compose.HELP_TEXT)
