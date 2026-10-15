"""Answer composer, Arabic (default) and English (pure functions over typed results)."""

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
BAND_EN = {TrustBand.GREEN: "trusted (green)", TrustBand.YELLOW: "medium trust (yellow)",
           TrustBand.RED: "high risk (red)", TrustBand.UNKNOWN: "unknown"}
MODE_EN = {"sea_lcl": "sea freight (LCL)", "sea_fcl_20": "sea freight, 20ft container",
           "sea_fcl_40": "sea freight, 40ft container", "sea_fcl_40hc": "sea freight, 40ft high-cube container",
           "air": "air freight", "rail": "rail freight", "road": "road freight"}
CUR_SYM = {"USD": "$"}

SERVICE_AR = {"sourcing": "البحث", "logistics": "حساب الشحن", "trust": "فحص الموثوقية", "tracking": "التتبع", "deals": "الصفقات"}
SERVICE_EN = {"sourcing": "search", "logistics": "freight calculation", "trust": "trust check", "tracking": "tracking", "deals": "deals"}

HELP_TEXT_EN = (
    "Welcome to Muwarrid. I can help you with:\n"
    "- Searching for a product, raw material or production line (new or used), e.g. \"I need a used pastry production line from China delivered to Baghdad\".\n"
    "- Full door-to-door cost, e.g. \"how much to ship 2 tons of plastic granules from Ningbo to Basra\".\n"
    "- Supplier trust check, e.g. \"is supplier sup_cn_001 trustworthy?\".\n"
    "- Validating a container or air waybill number, e.g. \"track container CSQU3054383\".\n"
    "- Shipment status (sign in), e.g. \"where is container CSQU3054383\".\n"
    "- Deal payment status (sign in), e.g. \"payment status of deal deal_abc\".\n"
    "- Comparing two listings, e.g. \"compare lst_a and lst_b\".\n"
    "- HS customs code, e.g. \"HS code for plastic chairs\"."
)


def help_text(lang: str = "ar") -> str:
    return HELP_TEXT_EN if lang == "en" else HELP_TEXT


def message_refusal(lang: str = "ar") -> str:
    return msg(lang, "ما أكدر أرسل رسائل خاصة للموردين نيابة عنك. أكدر أكتبلك مسودة تراجعها وترسلها بنفسك من محادثات التطبيق.",
               "I cannot send private messages to suppliers on your behalf. I can draft a message for you to review and send yourself from the in-app chat.")


def rfq_text(lang: str = "ar") -> str:
    return msg(lang, "لنشر طلب شراء واستلام عروض الموردين، استخدم تبويب الطلبات في التطبيق. جهّز المنتج والكمية ومدينة التسليم.",
               "To post a purchase request and receive supplier offers, use the Requests tab in the app. Have the product, quantity and delivery city ready.")


def msg(lang: str, ar: str, en: str) -> str:
    return en if lang == "en" else ar

HELP_TEXT = (
    "أهلاً بك في مُوَرِّد. أقدر أساعدك بـ:\n"
    "• البحث عن منتج أو مادة أولية أو خط إنتاج (جديد أو مستعمل)، مثال: «أريد خط إنتاج معجنات مستعمل من الصين يوصل بغداد».\n"
    "• حساب الكلفة الكاملة لحد الباب، مثال: «شكد كلفة شحن 2 طن حبيبات بلاستيك من ننغبو الى البصرة».\n"
    "• فحص موثوقية مورد، مثال: «هل المورد sup_cn_001 موثوق؟».\n"
    "• التحقق من رقم حاوية أو بوليصة جوية، مثال: «تتبع الحاوية CSQU3054383».\n"
    "• حالة شحنتك (بعد تسجيل الدخول)، مثال: «وين الحاوية CSQU3054383».\n"
    "• حالة الدفع لصفقة (بعد تسجيل الدخول)، مثال: «حالة الدفع للصفقة deal_abc».\n"
    "• مقارنة عرضين، مثال: «قارن lst_a مع lst_b».\n"
    "• الرمز الجمركي HS، مثال: «شنو رمز HS للكراسي البلاستيك»."
)


def money(m: Money) -> str:
    amt = f"{m.amount.quantize(Decimal(1)):,}"
    sym = CUR_SYM.get(m.currency)
    return f"{amt} {sym}" if sym else f"{amt} {m.currency}"


def price_range(listing: Listing, lang: str = "ar") -> str:
    lo, hi = listing.price.min, listing.price.max
    unit_name = (listing.unit or "") if lang == "en" else UNIT_AR.get(listing.unit or "", listing.unit)
    unit = f" / {unit_name}" if listing.unit else ""
    if lo.amount == hi.amount:
        return f"{money(lo)}{unit}"
    return f"{money(lo)} - {money(hi)}{unit}"


def listing_line(i: int, lst: Listing, gaz: Gazetteer, lang: str = "ar") -> str:
    if lang == "en":
        where = gaz.display_name(lst.supplier.location, "en")
        band = BAND_EN.get(lst.supplier.trust_band, "") if lst.supplier.trust_band else ""
        tail = f" - trust: {band}" if band else ""
        return f"{i}. {lst.title} | {price_range(lst, lang)} | {lst.supplier.name} ({where}){tail}"
    where = gaz.display_name(lst.supplier.location, "ar")
    band = BAND_AR.get(lst.supplier.trust_band, "") if lst.supplier.trust_band else ""
    tail = f" - ثقة: {band}" if band else ""
    return f"{i}. {lst.title_ar or lst.title} | {price_range(lst)} | {lst.supplier.name} ({where}){tail}"


def best_option(quote: LandedCostQuote) -> LandedCostOption | None:
    if not quote.options:
        return None
    rec = [o for o in quote.options if o.recommended]
    return rec[0] if rec else min(quote.options, key=lambda o: o.total.min.amount)


def quote_text(quote: LandedCostQuote, gaz: Gazetteer, lang: str = "ar") -> str:
    opt = best_option(quote)
    if opt is None:
        return msg(lang, "لم أحصل على خيارات شحن لهذا المسار.", "No shipping options were found for this route.")
    loc = "en" if lang == "en" else "ar"
    dest = gaz.display_name(quote.destination, loc) if quote.destination else ""
    modes = MODE_EN if lang == "en" else MODE_AR
    t, d = opt.total, opt.transit_days
    cheapest = min(quote.options, key=lambda o: o.total.min.amount)
    mode = modes.get(opt.mode.value, opt.mode.value)
    cheap = modes.get(cheapest.mode.value, cheapest.mode.value)
    if lang == "en":
        text = f"Estimated full landed cost to {dest}: {money(t.min)} to {money(t.max)} via {mode}, transit {d.min}-{d.max} days."
        if cheapest is not opt and cheapest.total.min.amount < t.min.amount:
            text += f" Cheapest: {cheap} from {money(cheapest.total.min)}."
        return text + " (an estimate, not a final quote)"
    text = (
        f"الكلفة الكاملة التقديرية لحد {dest}: {money(t.min)} إلى {money(t.max)} "
        f"عبر {mode}، والمدة {d.min}-{d.max} يوم."
    )
    if cheapest is not opt and cheapest.total.min.amount < t.min.amount:
        text += f" الأرخص: {cheap} من {money(cheapest.total.min)}."
    return text + " (تقدير وليس عرض سعر نهائي)"


def trust_text(t: TrustScore, lang: str = "ar") -> str:
    factors = sorted(t.factors, key=lambda f: -abs(f.impact))[:3]
    if lang == "en":
        text = f"Trust score for supplier {t.supplier_id}: {t.score}/100 - {BAND_EN.get(t.band, '')}."
        notes = [f.explanation for f in factors]
        return text + (" Main reasons: " + "; ".join(notes) + "." if notes else "")
    text = f"درجة الثقة للمورد {t.supplier_id}: {t.score}/100 - {BAND_AR.get(t.band, '')}."
    notes = [f.explanation_ar or f.explanation for f in factors]
    return text + (" أهم الأسباب: " + "، ".join(notes) + "." if notes else "")


def search_text(p: ParsedQuery, listings: list[Listing], total: int, gaz: Gazetteer, lang: str = "ar") -> str:
    if not listings:
        return msg(lang, "ما لقيت نتائج مطابقة. جرّب تغيّر الكلمات أو تشيل شرط (مثل البلد أو السعر).",
                   "No matching results. Try different words or drop a filter (such as country or price).")
    head = msg(lang, f"لقيت {total} نتيجة، هذي أفضل {len(listings)}:", f"Found {total} results, here are the top {len(listings)}:")
    note = msg(lang, "(أسعار استرشادية من الكتالوج وقد تتغير، أكّدها مع المورد)", "(indicative catalog prices that may change; confirm with the supplier)")
    return "\n".join([head, *[listing_line(i, lst, gaz, lang) for i, lst in enumerate(listings, 1)], note])


def need_destination(lang: str = "ar") -> str:
    return msg(lang, "حتى أحسب الكلفة لحد الباب، اكتب مدينة الوصول (مثلاً: بغداد أو البصرة أو أربيل).",
               "To calculate the door-to-door cost, tell me the destination city (e.g. Baghdad, Basra or Erbil).")
