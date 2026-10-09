"""Bilingual (English + Arabic) alert texts.

Every alert carries both languages; the app shows the user's locale and pushes are sent in
the device's locale. Product and supplier names come from sourcing as-is (``title_ar`` is
used for Arabic when sourcing provides it).
"""

from __future__ import annotations

from decimal import Decimal

from ff_notifications.domain.models import AlertMessage, ListingView, SearchQuery
from ff_notifications.domain.money import Money, format_percent

TITLE_NAME_LIMIT = 60
BODY_NAME_LIMIT = 80

_KIND_LABELS: dict[str, tuple[str, str]] = {
    "product": ("products", "منتجات"),
    "raw_material": ("raw materials", "مواد أولية"),
    "production_line": ("production lines", "خطوط إنتاج"),
}


def clip(text: str, limit: int) -> str:
    """Collapse whitespace and cut ``text`` to ``limit`` characters with an ellipsis."""
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 1, 1)].rstrip() + "…"


def listing_name(listing: ListingView, limit: int = TITLE_NAME_LIMIT) -> tuple[str, str]:
    """(English name, Arabic name) of a listing; Arabic falls back to the source title."""
    english = clip(listing.title, limit)
    arabic = clip(listing.title_ar, limit) if listing.title_ar else english
    return english, arabic


def search_label(query: SearchQuery) -> tuple[str, str]:
    """Short (English, Arabic) label that names a saved search in alert texts."""
    if query.q:
        text = clip(query.q, 40)
        return f"“{text}”", f"«{text}»"
    if query.category:
        text = clip(query.category, 40)
        return text, text
    if query.kind in _KIND_LABELS:
        return _KIND_LABELS[query.kind]
    return "your saved search", "بحثك المحفوظ"


def results_count_en(count: int) -> str:
    return "1 result" if count == 1 else f"{count} results"


def new_results_count_en(count: int) -> str:
    return "1 new result" if count == 1 else f"{count} new results"


def new_results_count_ar(count: int) -> str:
    """Arabic number agreement for "new result(s)"."""
    if count == 1:
        return "نتيجة جديدة"
    if count == 2:
        return "نتيجتان جديدتان"
    if 3 <= count <= 10:
        return f"{count} نتائج جديدة"
    return f"{count} نتيجة جديدة"


def new_alerts_count_ar(count: int) -> str:
    """Arabic number agreement for "new alert(s)"."""
    if count == 1:
        return "تنبيه جديد"
    if count == 2:
        return "تنبيهان جديدان"
    if 3 <= count <= 10:
        return f"{count} تنبيهات جديدة"
    return f"{count} تنبيهاً جديداً"


def _target_note(target_met: Money | None) -> tuple[str, str]:
    if target_met is None:
        return "", ""
    return (
        f" That meets your target of {target_met.format()}.",
        f" وهذا يحقق السعر المستهدف {target_met.format()}.",
    )


# --------------------------------------------------------------------------- listing watches


def price_drop_listing(
    listing: ListingView,
    old: Money,
    new: Money,
    pct: Decimal,
    target_met: Money | None = None,
) -> AlertMessage:
    name, name_ar = listing_name(listing)
    percent = format_percent(pct)
    note, note_ar = _target_note(target_met)
    return AlertMessage(
        title=f"Price drop: {name}",
        title_ar=f"انخفاض في السعر: {name_ar}",
        body=f"Now {new.format()} (was {old.format()}), {percent}% lower.{note}",
        body_ar=(
            f"السعر الآن {new.format()} بعد أن كان {old.format()}، "
            f"أي أقل بنسبة {percent}٪.{note_ar}"
        ),
    )


def below_target_listing(listing: ListingView, price: Money, target: Money) -> AlertMessage:
    name, name_ar = listing_name(listing)
    return AlertMessage(
        title=f"Target price reached: {name}",
        title_ar=f"وصل السعر إلى هدفك: {name_ar}",
        body=f"Now {price.format()}, at or below your target of {target.format()}.",
        body_ar=(
            f"السعر الآن {price.format()}، وهو عند السعر المستهدف {target.format()} أو أقل منه."
        ),
    )


def back_in_stock_listing(listing: ListingView) -> AlertMessage:
    name, name_ar = listing_name(listing)
    price = listing.price.format()
    return AlertMessage(
        title=f"Back in stock: {name}",
        title_ar=f"عاد متوفراً: {name_ar}",
        body=f"Available again at {price}.",
        body_ar=f"متوفر من جديد بسعر {price}.",
    )


def cheaper_equivalent(
    watched: ListingView, alternative: ListingView, pct: Decimal
) -> AlertMessage:
    name, name_ar = listing_name(watched)
    alt, alt_ar = listing_name(alternative, BODY_NAME_LIMIT)
    supplier = clip(alternative.supplier_name, BODY_NAME_LIMIT)
    percent = format_percent(pct)
    alt_price = alternative.price.format()
    watched_price = watched.price.format()
    return AlertMessage(
        title=f"Cheaper supplier found: {name}",
        title_ar=f"وجدنا مورّداً أرخص: {name_ar}",
        body=(
            f"{supplier or 'Another supplier'} offers {alt} at {alt_price}, "
            f"{percent}% below the {watched_price} you are watching."
        ),
        body_ar=(
            f"يعرض {supplier or 'مورّد آخر'} «{alt_ar}» بسعر {alt_price}، "
            f"أي أقل بنسبة {percent}٪ من السعر الذي تتابعه ({watched_price})."
        ),
    )


# --------------------------------------------------------------------------- saved searches


def price_drop_search(
    query: SearchQuery,
    best: ListingView,
    old: Money,
    new: Money,
    pct: Decimal,
    target_met: Money | None = None,
) -> AlertMessage:
    label, label_ar = search_label(query)
    item, item_ar = listing_name(best, BODY_NAME_LIMIT)
    percent = format_percent(pct)
    note, note_ar = _target_note(target_met)
    return AlertMessage(
        title=f"Lower price for {label}",
        title_ar=f"سعر أقل في {label_ar}",
        body=(
            f"Best offer is now {new.format()} (was {old.format()}), "
            f"{percent}% lower: {item}.{note}"
        ),
        body_ar=(
            f"أفضل عرض الآن {new.format()} بعد أن كان {old.format()}، "
            f"أي أقل بنسبة {percent}٪: {item_ar}.{note_ar}"
        ),
    )


def below_target_search(
    query: SearchQuery, best: ListingView, price: Money, target: Money
) -> AlertMessage:
    label, label_ar = search_label(query)
    item, item_ar = listing_name(best, BODY_NAME_LIMIT)
    return AlertMessage(
        title=f"Target price reached for {label}",
        title_ar=f"وصل السعر إلى هدفك في {label_ar}",
        body=(
            f"{item} is offered at {price.format()}, "
            f"at or below your target of {target.format()}."
        ),
        body_ar=(
            f"{item_ar} معروض بسعر {price.format()}، "
            f"وهو عند السعر المستهدف {target.format()} أو أقل منه."
        ),
    )


def back_in_stock_search(query: SearchQuery, total: int, best_price: Money | None) -> AlertMessage:
    label, label_ar = search_label(query)
    if best_price is not None:
        body = f"{results_count_en(total)} available again; best offer {best_price.format()}."
        body_ar = f"عدد النتائج المتاحة الآن: {total}، وأفضل عرض بسعر {best_price.format()}."
    else:
        body = f"{results_count_en(total)} available again."
        body_ar = f"عدد النتائج المتاحة الآن: {total}."
    return AlertMessage(
        title=f"Results are back for {label}",
        title_ar=f"عادت النتائج في {label_ar}",
        body=body,
        body_ar=body_ar,
    )


def new_results(
    query: SearchQuery, count: int, highlight: ListingView, highlight_is_cheapest: bool
) -> AlertMessage:
    label, label_ar = search_label(query)
    item, item_ar = listing_name(highlight, BODY_NAME_LIMIT)
    if highlight_is_cheapest:
        price = highlight.price.format()
        body = f"Cheapest new offer: {item} at {price}."
        body_ar = f"أرخص عرض جديد: {item_ar} بسعر {price}."
    else:
        body = f"Including {item}."
        body_ar = f"منها: {item_ar}."
    return AlertMessage(
        title=f"{new_results_count_en(count)} for {label}",
        title_ar=f"{new_results_count_ar(count)} في {label_ar}",
        body=body,
        body_ar=body_ar,
    )


# --------------------------------------------------------------------------- push


def push_summary(count: int) -> AlertMessage:
    """One push that stands for several alerts raised in the same evaluation run."""
    english = "1 new alert" if count == 1 else f"{count} new alerts"
    return AlertMessage(
        title=f"You have {english}",
        title_ar=f"لديك {new_alerts_count_ar(count)}",
        body="Price drops and better offers on your watchlist. Open the app to see them.",
        body_ar="انخفاض في الأسعار وعروض أفضل في قائمة متابعتك. افتح التطبيق للاطلاع عليها.",
    )
