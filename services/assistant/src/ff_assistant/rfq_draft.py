"""RFQ draft card: fields come only from the user's own text; nothing is created or sent anywhere."""

from __future__ import annotations

from decimal import Decimal

from ff_assistant import compose
from ff_assistant.domain.cards import Card, CardType, row
from ff_assistant.domain.gazetteer import Gazetteer
from ff_assistant.domain.query import ParsedQuery
from ff_assistant.tools import ToolOutput

DEEP_LINK = "/requests/new"
REQUIRED = ("product", "quantity", "destination")
LABELS = {  # key -> (en, ar)
    "product": ("Product", "المنتج"), "quantity": ("Quantity", "الكمية"), "unit": ("Unit", "الوحدة"),
    "destination": ("Delivery to", "جهة التسليم"), "target_price": ("Target price", "السعر المستهدف"),
}


def _plain(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    return s if "." not in s else s.rstrip("0").rstrip(".")


def build_rfq_draft(p: ParsedQuery, gaz: Gazetteer) -> ToolOutput:
    L = p.language
    product = p.query or None
    unit_en = p.unit
    unit_ar = compose.UNIT_AR.get(p.unit or "", p.unit)
    values: dict[str, tuple[str | None, str | None]] = {
        "product": (product, product),
        "quantity": (_plain(p.quantity) if p.quantity is not None else None,) * 2,
        "unit": (unit_en, unit_ar),
        "destination": ((gaz.display_name(p.destination, "en"), gaz.display_name(p.destination, "ar")) if p.destination else (None, None)),
        "target_price": ((f"{_plain(p.budget.amount)} {p.budget.currency}",) * 2 if p.budget else (None, None)),
    }
    missing = [k for k in REQUIRED if values[k][0] is None]
    if p.quantity is not None and p.unit is None:
        missing.append("unit")
    rows = [row(k, LABELS[k][0], LABELS[k][1], v[0], v[1]) for k, v in values.items()]
    refs = {"deep_link": DEEP_LINK, "draft": "true", "missing": ",".join(missing)}
    refs.update({f"prefill_{k}": v[0] for k, v in values.items() if v[0] is not None})
    card = Card(
        type=CardType.RFQ_DRAFT, title="Purchase request draft", title_ar="مسودة طلب شراء",
        severity="warning" if missing else "info", rows=rows, refs=refs,
        footnote="Draft only: nothing has been posted. Review and publish it from the Requests tab.",
        footnote_ar="مسودة فقط: لم يُنشر شيء. راجعها وانشرها من تبويب الطلبات.",
    )
    names = {k: LABELS[k][0 if L == "en" else 1] for k in LABELS}
    if missing:
        miss = ("، " if L != "en" else ", ").join(names[k] for k in missing)
        text = compose.msg(L, f"جهزت مسودة طلب الشراء لكن ينقصها: {miss}. أكمل الناقص ثم انشرها من تبويب الطلبات (لم أنشر شيئاً).",
                           f"I prepared a purchase request draft but it is missing: {miss}. Complete it and publish it from the Requests tab (nothing was posted).")
    else:
        text = compose.msg(L, "جهزت مسودة طلب الشراء بالبيانات التي ذكرتها. راجعها وانشرها من تبويب الطلبات (لم أنشر شيئاً).",
                           "I prepared your purchase request draft from the details you gave. Review it and publish it from the Requests tab (nothing was posted).")
    return ToolOutput(text, cards=[card])
