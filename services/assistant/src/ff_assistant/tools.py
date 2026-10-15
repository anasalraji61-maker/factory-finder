"""Assistant tools: shipment status, deal/payment status, listing comparison, HS-code lookup.

Each tool calls other services only through the client interfaces in ``clients/``, degrades to a
``<svc>_unavailable`` warning, and returns text + structured cards. Rules:

* Identity comes only from the caller's ``user_id`` (X-User-Id set by the gateway). It is never read
  from the message text, never sent to an LLM, and user-scoped tools make NO downstream call without it.
* Third-party text (titles, carrier events, HS descriptions) passes through ``guard.Sanitizer`` first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from ff_assistant import compose
from ff_assistant.clients.base import DealInfo, ShipmentInfo
from ff_assistant.domain.cards import Card, CardColumn, CardRow, CardType, notice, row
from ff_assistant.domain.models import Listing, Money, TrustScore
from ff_assistant.domain.query import ParsedQuery
from ff_assistant.guard import Sanitizer

if TYPE_CHECKING:
    from ff_assistant.service import Assistant

STATUS_AR = {
    "booked": "تم الحجز", "gate_in": "دخلت الميناء", "loaded": "تم التحميل", "departed": "غادرت", "in_transit": "في الطريق",
    "transshipment": "في عملية ترانزيت", "arrived": "وصلت", "discharged": "تم التفريغ", "customs_hold": "محتجزة بالجمارك",
    "released": "تم الإفراج", "out_for_delivery": "خرجت للتسليم", "delivered": "تم التسليم", "exception": "مشكلة بالشحنة",
}
STATUS_EN = {k: k.replace("_", " ") for k in STATUS_AR}
DEAL_AR = {"pending_payment": "بانتظار الدفع", "paid": "مدفوعة", "in_fulfilment": "قيد التنفيذ", "completed": "مكتملة",
           "disputed": "متنازع عليها", "cancelled": "ملغاة", "refunded": "مستردة"}
DEAL_EN = {k: k.replace("_", " ") for k in DEAL_AR}
PAY_AR = {"open": "بانتظار الدفع", "paid": "مدفوعة", "refunded": "مستردة", None: "لا توجد فاتورة بعد"}
PAY_EN = {"open": "awaiting payment", "paid": "paid", "refunded": "refunded", None: "no invoice yet"}
SEVERITY_SHIPMENT = {"delivered": "ok", "exception": "error", "customs_hold": "warning"}
SEVERITY_DEAL = {"paid": "ok", "completed": "ok", "in_fulfilment": "ok", "disputed": "error", "cancelled": "warning",
                 "refunded": "warning", "pending_payment": "info"}


@dataclass
class ToolOutput:
    text: str
    cards: list[Card] = field(default_factory=list)
    listings: list[Listing] = field(default_factory=list)
    trust: TrustScore | None = None
    quote: Any = None


def _m(d: dict[str, Any] | None) -> str | None:
    try:
        return compose.money(Money.model_validate(d)) if d else None
    except ValueError:
        return None


def _place(loc: dict[str, Any] | None, a: Assistant, san: Sanitizer) -> tuple[str | None, str | None]:
    if not loc or not loc.get("country_code"):
        return None, None
    from ff_assistant.domain.models import Location

    place = Location(country_code=loc["country_code"], city=san.opt(loc.get("city"), 60))
    return a.gaz.display_name(place, "en"), a.gaz.display_name(place, "ar")


class Tools:
    def __init__(self, assistant: Assistant) -> None:
        self.a = assistant

    # -- (a) shipment status ------------------------------------------------------------------
    async def shipment_status(self, p: ParsedQuery, user_id: str | None, warnings: list[str], san: Sanitizer) -> ToolOutput:
        L = p.language
        if not user_id:
            return self._auth_required(L, "shipments", "تتبع شحناتك", "your shipments")
        if not p.reference:
            return ToolOutput(compose.msg(L, "اكتب رقم الحاوية أو بوليصة الشحن الجوي حتى أجيب حالة الشحنة.", "Send the container number or air waybill so I can look up the shipment."))
        ship = await self.a._guard("tracking", self.a.c.tracking.find_shipment(user_id, p.reference), warnings)
        if ship is None:
            if "tracking_unavailable" in warnings:
                return ToolOutput(compose.msg(L, f"خدمة التتبع غير متاحة هسه، ما كدرت أجيب حالة {p.reference}.", f"The tracking service is unavailable, so I could not get the status of {p.reference}."),
                                  [notice("tracking_unavailable", "Tracking unavailable", "التتبع غير متاح", "warning")])
            return ToolOutput(
                compose.msg(L, f"ما لقيت {p.reference} ضمن شحناتك. أضفه من تبويب الشحنات حتى أتابعه.", f"I could not find {p.reference} among your shipments. Add it from the Shipments tab to follow it."),
                [notice("shipment_not_found", "Shipment not found", "الشحنة غير موجودة بين شحناتك", "info")])
        ship = ship.model_copy(update={"id": san.ident(ship.id), "reference": san.text(ship.reference, 40), "status": san.text(ship.status, 30),
                                       "eta": san.opt(ship.eta, 32)})
        card = self._shipment_card(ship, san)
        return ToolOutput(self._shipment_text(ship, card, L, san), [card])

    def _shipment_card(self, s: ShipmentInfo, san: Sanitizer) -> Card:
        a = self.a
        o_en, o_ar = _place(s.origin, a, san)
        d_en, d_ar = _place(s.destination, a, san)
        rows = [row("status", "Status", "الحالة", STATUS_EN.get(s.status, san.text(s.status, 30)), STATUS_AR.get(s.status, san.text(s.status, 30))),
                row("progress", "Progress", "التقدم", f"{s.progress_percent}%")]
        if s.eta:
            rows.append(row("eta", "ETA", "موعد الوصول المتوقع", s.eta[:10]))
        if s.delayed:
            hrs = f" (+{s.delay_hours}h)" if s.delay_hours else ""
            rows.append(row("delayed", "Delayed", "متأخرة", "yes" + hrs, "نعم" + hrs))
        if s.carrier and s.carrier.get("name"):
            rows.append(row("carrier", "Carrier", "الناقل", san.text(s.carrier.get("name"), 60), san.opt(s.carrier.get("name_ar"), 60)))
        if o_en and d_en:
            rows.append(row("route", "Route", "المسار", f"{o_en} → {d_en}", f"{o_ar} ← {d_ar}"))
        if s.events:
            ev = max(s.events, key=lambda e: str(e.get("timestamp", "")))
            rows.append(row("last_event", "Last event", "آخر حدث", san.text(ev.get("description"), 120), san.opt(ev.get("description_ar"), 120)))
        stale = bool(s.warning)
        return Card(type=CardType.SHIPMENT_STATUS, title=f"Shipment {s.reference}", title_ar=f"الشحنة {s.reference}",
                    severity="warning" if stale else SEVERITY_SHIPMENT.get(s.status, "info"), rows=rows, refs={"shipment_id": s.id, "reference": s.reference},
                    footnote="Data may be stale (tracking provider issue)." if stale else None,
                    footnote_ar="البيانات قد تكون قديمة (مشكلة عند مزوّد التتبع)." if stale else None)

    def _shipment_text(self, s: ShipmentInfo, card: Card, L: str, san: Sanitizer) -> str:
        r = {x.key: x for x in card.rows}
        st = (STATUS_EN if L == "en" else STATUS_AR).get(s.status, s.status)
        parts = [compose.msg(L, f"الشحنة {s.reference}: {st}، التقدم {s.progress_percent}%.", f"Shipment {s.reference}: {st}, progress {s.progress_percent}%.")]
        if "eta" in r:
            parts.append(compose.msg(L, f"الوصول المتوقع {r['eta'].value}.", f"Expected arrival {r['eta'].value}."))
        if "delayed" in r:
            parts.append(compose.msg(L, "الشحنة متأخرة عن الموعد الأصلي.", "The shipment is behind its original schedule."))
        if "last_event" in r:
            ev = r["last_event"]
            parts.append(compose.msg(L, f"آخر حدث: {ev.value_ar or ev.value}.", f"Last event: {ev.value}."))
        if card.footnote:
            parts.append(compose.msg(L, card.footnote_ar or "", card.footnote))
        return " ".join(parts)

    # -- (b) deal / payment status ------------------------------------------------------------
    async def deal_status(self, p: ParsedQuery, user_id: str | None, warnings: list[str], san: Sanitizer) -> ToolOutput:
        L = p.language
        if not user_id:  # never touch rfq/payments data without a forwarded identity
            return self._auth_required(L, "deals", "حالة صفقاتك ودفعاتك", "your deals and payments")
        if not p.deal_id:
            return ToolOutput(compose.msg(L, "اكتب رقم الصفقة (مثل deal_xxx) حتى أجيب حالة الدفع.", "Send the deal id (e.g. deal_xxx) so I can check its payment status."))
        if self.a.c.deals is None:
            warnings.append("deals_unavailable")
            return ToolOutput(compose.msg(L, "ما كدرت أجيب حالة الصفقة هسه.", "I could not fetch the deal status right now."))
        deal = await self.a._guard("deals", self.a.c.deals.get_deal(user_id, p.deal_id), warnings)
        if deal is None and "deals_unavailable" in warnings:
            return ToolOutput(compose.msg(L, "خدمة الصفقات غير متاحة هسه، جرّب بعد شوي.", "The deals service is unavailable, please try again shortly."))
        # same answer for "no such deal" and "not your deal": no existence leak; defensive party check
        if deal is None or user_id not in (deal.buyer_id, deal.supplier_user_id):  # fail closed on missing party ids
            return ToolOutput(compose.msg(L, f"ما لقيت الصفقة {p.deal_id} ضمن صفقاتك.", f"I could not find deal {p.deal_id} among your deals."),
                              [notice("deal_not_found", "Deal not found", "الصفقة غير موجودة بين صفقاتك")])
        deal = deal.model_copy(update={"id": san.ident(deal.id), "status": san.text(deal.status, 30),
                                       "payment": {k: san.text(str(v), 20) if v is not None else None for k, v in (deal.payment or {}).items()}})
        card = self._deal_card(deal, user_id)
        return ToolOutput(self._deal_text(deal, L), [card])

    def _deal_card(self, d: DealInfo, user_id: str) -> Card:
        pay = d.payment or {}
        role = ("buyer", "مشتري") if d.buyer_id == user_id else ("supplier", "مورّد")
        rows = [row("status", "Deal status", "حالة الصفقة", DEAL_EN.get(d.status, d.status), DEAL_AR.get(d.status, d.status)),
                row("role", "Your role", "دورك", role[0], role[1])]
        if sub := _m(d.subtotal):
            rows.append(row("subtotal", "Deal amount", "مبلغ الصفقة", sub))
        com = d.commission or {}
        if (c := _m(com.get("amount"))) is not None:
            rows.append(row("commission", "Commission", "العمولة", c + (" (est.)" if com.get("is_estimate") else ""), c + (" (تقديري)" if com.get("is_estimate") else "")))
        for key, en, ar in (("commission", "Commission payment", "دفع العمولة"), ("deal_payment", "Deal payment", "دفع الصفقة")):
            rows.append(row(f"pay_{key}", en, ar, PAY_EN.get(pay.get(key), str(pay.get(key))), PAY_AR.get(pay.get(key), str(pay.get(key)))))
        if d.delivered_at:
            rows.append(row("delivered_at", "Delivered", "تاريخ التسليم", d.delivered_at[:10]))
        if d.completed_at:
            rows.append(row("completed_at", "Completed", "تاريخ الإكمال", d.completed_at[:10]))
        return Card(type=CardType.DEAL_STATUS, title=f"Deal {d.id}", title_ar=f"الصفقة {d.id}", severity=SEVERITY_DEAL.get(d.status, "info"),
                    rows=rows, refs={"deal_id": d.id}, footnote="Payments are confirmed by the payment provider; this is a read-only status.",
                    footnote_ar="تأكيد الدفع يتم من مزوّد الدفع؛ هذه حالة للقراءة فقط.")

    def _deal_text(self, d: DealInfo, L: str) -> str:
        pay = d.payment or {}
        st = (DEAL_EN if L == "en" else DEAL_AR).get(d.status, d.status)
        pm = PAY_EN if L == "en" else PAY_AR
        text = compose.msg(L, f"الصفقة {d.id}: {st}.", f"Deal {d.id}: {st}.")
        text += compose.msg(L, f" دفع الصفقة: {pm.get(pay.get('deal_payment'))}، دفع العمولة: {pm.get(pay.get('commission'))}.",
                            f" Deal payment: {pm.get(pay.get('deal_payment'))}; commission payment: {pm.get(pay.get('commission'))}.")
        if sub := _m(d.subtotal):
            text += compose.msg(L, f" مبلغ الصفقة {sub}.", f" Deal amount {sub}.")
        return text

    # -- (c) compare two listings ---------------------------------------------------------------
    async def compare(self, p: ParsedQuery, warnings: list[str], san: Sanitizer) -> ToolOutput:
        L = p.language
        ids = p.listing_ids[:2]
        if len(ids) < 2:
            return ToolOutput(compose.msg(L, "اكتب رقمين لعروض (مثل lst_xxx و lst_yyy) حتى أقارن بينهم.", "Send two listing ids (e.g. lst_xxx and lst_yyy) so I can compare them."))
        if len(p.listing_ids) > 2:
            warnings.append("compare_limited_to_two")
        found = [await self.a._guard("sourcing", self.a.c.sourcing.get_listing(i), warnings) for i in ids]
        if "sourcing_unavailable" in warnings:
            return ToolOutput(compose.msg(L, "خدمة البحث غير متاحة هسه، ما كدرت أقارن.", "The search service is unavailable, so I could not compare."))
        missing = [i for i, f in zip(ids, found, strict=True) if f is None]
        if missing:
            return ToolOutput(compose.msg(L, f"ما لقيت العرض: {'، '.join(missing)}.", f"I could not find listing: {', '.join(missing)}."),
                              [notice("listing_not_found", "Listing not found", "العرض غير موجود", "warning")])
        a, b = (san.listing(f) for f in found if f is not None)
        trusts: list[TrustScore | None] = []
        for lst in (a, b):
            t = await self.a._supplier_trust(lst, warnings)
            trusts.append(san.trust(t) if t else None)
        quotes: list[Any] = [None, None]
        if p.destination:
            qp = p.model_copy(update={"origin": None, "quantity": None, "unit": None})
            quotes = [await self.a._quote_for(qp, lst, warnings) for lst in (a, b)]
        card = self._compare_card(a, b, trusts, quotes, san)
        return ToolOutput(self._compare_text(a, b, trusts, card, L), [card], listings=[a, b], trust=trusts[0], quote=quotes[0])

    def _compare_card(self, a: Listing, b: Listing, trusts: list[TrustScore | None], quotes: list[Any], san: Sanitizer) -> Card:
        gaz = self.a.gaz
        ls = (a, b)

        def mid(x: Listing) -> Decimal:
            return (x.price.min.amount + x.price.max.amount) / 2

        rows: list[CardRow] = [
            CardRow(key="title", label="Product", label_ar="المنتج", values=[x.title for x in ls]),
            CardRow(key="condition", label="Condition", label_ar="الحالة", values=[(x.condition.value if x.condition else "-") for x in ls]),
        ]
        comparable = a.price.min.currency == b.price.min.currency and (a.unit or "") == (b.unit or "")
        price = CardRow(key="price", label="Unit price", label_ar="سعر الوحدة", values=[compose.price_range(x, "en") for x in ls])
        if comparable and mid(a) != mid(b):
            price.highlight = 0 if mid(a) < mid(b) else 1
        rows.append(price)
        rows.append(CardRow(key="moq", label="Min. order", label_ar="الحد الأدنى للطلب", values=[str(x.moq) if x.moq else "-" for x in ls]))
        rows.append(CardRow(key="supplier", label="Supplier", label_ar="المورد",
                            values=[f"{x.supplier.name} ({gaz.display_name(x.supplier.location, 'en')})" for x in ls]))
        scores = [t.score if t else x.supplier.trust_score for t, x in zip(trusts, ls, strict=True)]
        tr = CardRow(key="trust", label="Trust score", label_ar="درجة الثقة", values=[f"{s}/100" if s is not None else "-" for s in scores])
        if None not in scores and scores[0] != scores[1]:
            tr.highlight = 0 if scores[0] > scores[1] else 1  # type: ignore[operator]
        rows.append(tr)
        if any(x.lead_time_days for x in ls):
            rows.append(CardRow(key="lead_time", label="Lead time (days)", label_ar="مدة التجهيز (يوم)",
                                values=[f"{x.lead_time_days.min}-{x.lead_time_days.max}" if x.lead_time_days else "-" for x in ls]))
        if any(quotes):
            vals = []
            for q in quotes:
                o = compose.best_option(q) if q else None
                vals.append(f"{compose.money(o.total.min)} - {compose.money(o.total.max)}" if o else "-")
            rows.append(CardRow(key="landed", label="Est. landed cost (min. order)", label_ar="الكلفة الكاملة التقديرية (للحد الأدنى)", values=vals))
        return Card(type=CardType.LISTING_COMPARISON, title="Listing comparison", title_ar="مقارنة العروض", rows=rows,
                    columns=[CardColumn(id=x.id, title=x.title, title_ar=x.title_ar) for x in ls], refs={"listing_a": a.id, "listing_b": b.id},
                    footnote="Indicative comparison from catalog data; confirm details with the supplier.",
                    footnote_ar="مقارنة استرشادية من بيانات الكتالوج؛ أكّد التفاصيل مع المورد.")

    def _compare_text(self, a: Listing, b: Listing, trusts: list[TrustScore | None], card: Card, L: str) -> str:
        r = {x.key: x for x in card.rows}
        ls = (a, b)
        name = [(x.title if L == "en" else (x.title_ar or x.title)) for x in ls]
        lines = [compose.msg(L, f"مقارنة: (1) {name[0]} مقابل (2) {name[1]}", f"Comparison: (1) {name[0]} vs (2) {name[1]}")]
        for i, x in enumerate(ls, 1):
            lines.append(f"{i}. {compose.price_range(x, L)} | {x.supplier.name}" + (f" | {r['trust'].values[i - 1]}" if r["trust"].values and r["trust"].values[i - 1] != "-" else ""))
        verdict = []
        if r["price"].highlight is not None:
            verdict.append(compose.msg(L, f"الأرخص سعراً: ({r['price'].highlight + 1})", f"Lower price: ({r['price'].highlight + 1})"))
        elif a.price.min.currency != b.price.min.currency or (a.unit or "") != (b.unit or ""):
            verdict.append(compose.msg(L, "الأسعار بوحدات/عملات مختلفة فلا تُقارن مباشرة", "Prices use different units/currencies, so they are not directly comparable"))
        if r["trust"].highlight is not None:
            verdict.append(compose.msg(L, f"الأعلى ثقة: ({r['trust'].highlight + 1})", f"Higher trust: ({r['trust'].highlight + 1})"))
        if verdict:
            lines.append(("؛ " if L != "en" else "; ").join(verdict) + ".")
        lines.append(compose.msg(L, "(مقارنة استرشادية، أكّد التفاصيل مع المورد)", "(indicative comparison, confirm details with the supplier)"))
        return "\n".join(lines)

    # -- (d) HS-code lookup -----------------------------------------------------------------------
    async def hs_lookup(self, p: ParsedQuery, warnings: list[str], san: Sanitizer) -> ToolOutput:
        L = p.language
        cc = p.destination.country_code if p.destination else "IQ"
        logi = self.a.c.logistics
        if p.hs_code:
            if len(p.hs_code) < 6:
                return ToolOutput(compose.msg(L, "رمز HS يتكون من 6 أرقام على الأقل.", "An HS code has at least 6 digits."))
            one = await self.a._guard("logistics", logi.hs_detail(p.hs_code, cc), warnings)
            items = [one] if one else []
        elif p.hs_query:
            res = await self.a._guard("logistics", logi.hs_search(p.hs_query, cc, 3), warnings)
            items = (res.items if res else [])[:3]
        else:
            return ToolOutput(compose.msg(L, "اكتب اسم المنتج أو رمز HS (6 أرقام) حتى أدور على الرمز الجمركي.", "Send a product name or an HS code (6 digits) so I can look up the customs code."))
        if "logistics_unavailable" in warnings:
            return ToolOutput(compose.msg(L, "خدمة الجمارك غير متاحة هسه.", "The customs lookup is unavailable right now."))
        if not items:
            return ToolOutput(compose.msg(L, "ما لقيت رمز جمركي مطابق. جرّب وصف أبسط للمنتج.", "No matching HS code found. Try a simpler product description."),
                              [notice("hs_not_found", "No HS match", "لا يوجد رمز مطابق")])
        rows = []
        items = [it.model_copy(update={"code": san.ident(it.code)}) for it in items]
        for i, it in enumerate(items, 1):
            duty = f"~{it.typical_duty_percent_hint:g}%" if it.typical_duty_percent_hint is not None else "-"
            rows.append(CardRow(key=f"hs_{i}", label=it.code, label_ar=it.code, value=f"{san.text(it.description_en, 120)} | duty {duty}",
                                value_ar=f"{san.text(it.description_ar, 120)} | رسوم {duty}"))
        card = Card(type=CardType.HS_CODE, title="HS code lookup", title_ar="البحث عن الرمز الجمركي", rows=rows, refs={"hs_code": items[0].code, "destination_country": cc},
                    footnote="Indicative only; confirm the code and duties with a customs broker.", footnote_ar="استرشادي فقط؛ أكّد الرمز والرسوم مع مخلّص جمركي.")
        top = items[0]
        desc = san.text(top.description_en, 120) if L == "en" else san.text(top.description_ar or top.description_en, 120)
        text = compose.msg(L, f"أقرب رمز جمركي: {top.code} ({desc}).", f"Closest HS code: {top.code} ({desc}).")
        if len(items) > 1:
            text += compose.msg(L, " بدائل: " + "، ".join(i.code for i in items[1:]) + ".", " Alternatives: " + ", ".join(i.code for i in items[1:]) + ".")
        if top.typical_duty_percent_hint is not None:
            text += compose.msg(L, f" الرسوم التقريبية للعراق ~{top.typical_duty_percent_hint:g}%." if cc == "IQ" else f" الرسوم التقريبية ~{top.typical_duty_percent_hint:g}%.",
                                f" Typical duty ~{top.typical_duty_percent_hint:g}%.")
        return ToolOutput(text + compose.msg(L, " (استرشادي، أكّد مع مخلّص جمركي)", " (indicative, confirm with a customs broker)"), [card])

    # -- shared ------------------------------------------------------------------------------------
    def _auth_required(self, L: str, code: str, ar: str, en: str) -> ToolOutput:
        return ToolOutput(compose.msg(L, f"سجّل الدخول حتى أكدر أعرض {ar}.", f"Please sign in so I can show {en}."),
                          [notice(f"auth_required_{code}", "Sign in required", "يلزم تسجيل الدخول", "warning")])
