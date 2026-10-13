"""Arabic answer composer (pure functions over typed results)."""

from __future__ import annotations

from decimal import Decimal

from ff_assistant.domain.gazetteer import Gazetteer
from ff_assistant.domain.models import (
    LandedCostOption,
    LandedCostQuote,
    Listing,
    Money,
    TrustBand,
    TrustScore,
)
from ff_assistant.domain.query import ParsedQuery

BAND_AR = {
    TrustBand.GREEN: "موثوق (أخضر)",
    TrustBand.YELLOW: "ثقة متوسطة (أصفر)",
    TrustBand.RED: "مخاطرة عالية (أحمر)",
    TrustBand.UNKNOWN: "غير معروف",
}
MODE_AR = {
    "sea_lcl": "شحن بحري (حمولة مجمّعة)",
    "sea_fcl_20": "شحن بحري حاوية 20 قدم",
    "sea_fcl_40": "شحن بحري حاوية 40 قدم",
    "sea_fcl_40hc": "شحن بحري حاوية 40 قدم عالية",
    "air": "شحن جوي",
    "rail": "شحن بالقطار",
    "road": "شحن بري",
}
UNIT_AR = {"ton": "طن", "kg": "كغم", "piece": "قطعة", "unit": "وحدة", "set": "طقم", "container": "حاوية",
           "meter": "متر", "liter": "لتر"}
CUR_SYM = {"USD": "$"}

HELP_TEXT = (
    "أهلاً بك في مُوَرِّد. أقدر أساعدك بـ:\n"
    "• البحث عن منتج أو مادة أولية أو خط إنتاج (جديد أو مستعمل)، مثال: «أريد خط إنتاج معجنات مستعمل من الصين يوصل بغداد».\n"
    "• حساب الكلفة الكاملة لحد الباب، مثال: «شكد كلفة شحن 2 طن حبيبات بلاستيك من ننغبو الى البصرة».\n"
    "• فحص موثوقية مورد، مثال: «هل المورد sup_cn_001 موثوق؟».\n"
    "• التحقق من رقم حاوية أو بوليصة جوية، مثال: «تتبع الحاوية CSQU3054383»."
)


def money(m: Money) -> str:
    amt = f"{m.amount.quantize(Decimal(1)):,}"
    sym = CUR_SYM.get(m.currency)
    return f"{amt} {sym}" if sym else f"{amt} {m.currency}"


def price_range(listing: Listing) -> str:
    lo, hi = listing.price.min, listing.price.max
    unit = f" / {UNIT_AR.get(listing.unit or '', listing.unit)}" if listing.unit else ""
    if lo.amount == hi.amount:
        return f"{money(lo)}{unit}"
    return f"{money(lo)} - {money(hi)}{unit}"


def listing_line(i: int, lst: Listing, gaz: Gazetteer) -> str:
    where = gaz.display_name(lst.supplier.location, "ar")
    band = BAND_AR.get(lst.supplier.trust_band, "") if lst.supplier.trust_band else ""
    tail = f" - ثقة: {band}" if band else ""
    return f"{i}. {lst.title_ar or lst.title} | {price_range(lst)} | {lst.supplier.name} ({where}){tail}"


def best_option(quote: LandedCostQuote) -> LandedCostOption | None:
    if not quote.options:
        return None
    rec = [o for o in quote.options if o.recommended]
    return rec[0] if rec else min(quote.options, key=lambda o: o.total.min.amount)


def quote_text(quote: LandedCostQuote, gaz: Gazetteer) -> str:
    opt = best_option(quote)
    if opt is None:
        return "لم أحصل على خيارات شحن لهذا المسار."
    dest = gaz.display_name(quote.destination, "ar") if quote.destination else ""
    t, d = opt.total, opt.transit_days
    cheapest = min(quote.options, key=lambda o: o.total.min.amount)
    text = (
        f"الكلفة الكاملة التقديرية لحد {dest}: {money(t.min)} إلى {money(t.max)} "
        f"عبر {MODE_AR.get(opt.mode.value, opt.mode.value)}، والمدة {d.min}-{d.max} يوم."
    )
    if cheapest is not opt and cheapest.total.min.amount < t.min.amount:
        text += f" الأرخص: {MODE_AR.get(cheapest.mode.value, cheapest.mode.value)} من {money(cheapest.total.min)}."
    return text + " (تقدير وليس عرض سعر نهائي)"


def trust_text(t: TrustScore) -> str:
    text = f"درجة الثقة للمورد {t.supplier_id}: {t.score}/100 - {BAND_AR.get(t.band, '')}."
    notes = [f.explanation_ar or f.explanation for f in sorted(t.factors, key=lambda f: -abs(f.impact))[:3]]
    return text + (" أهم الأسباب: " + "، ".join(notes) + "." if notes else "")


def search_text(p: ParsedQuery, listings: list[Listing], total: int, gaz: Gazetteer) -> str:
    if not listings:
        return "ما لقيت نتائج مطابقة. جرّب تغيّر الكلمات أو تشيل شرط (مثل البلد أو السعر)."
    lines = [f"لقيت {total} نتيجة، هذي أفضل {len(listings)}:"]
    lines += [listing_line(i, lst, gaz) for i, lst in enumerate(listings, 1)]
    return "\n".join(lines)


def need_destination() -> str:
    return "حتى أحسب الكلفة لحد الباب، اكتب مدينة الوصول (مثلاً: بغداد أو البصرة أو أربيل)."
