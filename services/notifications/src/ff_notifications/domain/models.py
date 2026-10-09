"""Domain entities and value objects (pure: no I/O, no framework imports)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields, replace
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from ff_notifications.domain.money import Money, format_amount, parse_amount

SEEN_IDS_CAP = 500
"""Maximum number of listing ids remembered per saved search (oldest are forgotten first)."""


class WatchType(StrEnum):
    LISTING = "listing"
    SEARCH = "search"


class RuleKind(StrEnum):
    PRICE_DROP = "price_drop"
    BELOW_TARGET = "below_target"
    CHEAPER_EQUIVALENT = "cheaper_equivalent"
    BACK_IN_STOCK = "back_in_stock"
    NEW_RESULTS = "new_results"


class TrustBand(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, value: object) -> TrustBand:
        """Lenient parse: anything unexpected becomes ``unknown``."""
        if isinstance(value, str):
            try:
                return cls(value.strip().lower())
            except ValueError:
                return cls.UNKNOWN
        return cls.UNKNOWN

    @property
    def rank(self) -> int:
        """Lower is more trustworthy; used to break price ties deterministically."""
        return _TRUST_RANK[self]


_TRUST_RANK = {
    TrustBand.GREEN: 0,
    TrustBand.YELLOW: 1,
    TrustBand.UNKNOWN: 2,
    TrustBand.RED: 3,
}


class Platform(StrEnum):
    ANDROID = "android"
    IOS = "ios"


class Locale(StrEnum):
    AR = "ar"
    EN = "en"


LISTING_KINDS: tuple[str, ...] = ("product", "raw_material", "production_line")
SEARCH_CONDITIONS: tuple[str, ...] = ("new", "used", "any")


# --------------------------------------------------------------------------- saved searches


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """A saved search: the filter parameters of sourcing ``GET /v1/search`` (paging excluded)."""

    q: str | None = None
    kind: str | None = None
    condition: str | None = None
    origin_country: str | None = None
    category: str | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    moq_max: int | None = None
    verified_only: bool | None = None

    def to_json(self) -> dict[str, Any]:
        """JSON form used by the API and by storage (``None`` fields omitted)."""
        data: dict[str, Any] = {}
        for name in ("q", "kind", "condition", "origin_country", "category"):
            value = getattr(self, name)
            if value is not None:
                data[name] = value
        for name in ("min_price", "max_price"):
            value = getattr(self, name)
            if value is not None:
                data[name] = format_amount(value)
        if self.moq_max is not None:
            data["moq_max"] = self.moq_max
        if self.verified_only is not None:
            data["verified_only"] = self.verified_only
        return data

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SearchQuery:
        def opt_decimal(key: str) -> Decimal | None:
            value = data.get(key)
            return None if value is None else parse_amount(value)

        moq = data.get("moq_max")
        verified = data.get("verified_only")
        return cls(
            q=data.get("q"),
            kind=data.get("kind"),
            condition=data.get("condition"),
            origin_country=data.get("origin_country"),
            category=data.get("category"),
            min_price=opt_decimal("min_price"),
            max_price=opt_decimal("max_price"),
            moq_max=None if moq is None else int(moq),
            verified_only=None if verified is None else bool(verified),
        )

    def to_params(self) -> dict[str, str]:
        """Query-string parameters for sourcing ``GET /v1/search``."""
        params: dict[str, str] = {}
        for key, value in self.to_json().items():
            if isinstance(value, bool):
                params[key] = "true" if value else "false"
            else:
                params[key] = str(value)
        return params

    def canonical_key(self) -> str:
        """Stable identity used to detect an owner saving the same search twice."""
        data = self.to_json()
        if self.q is not None:
            data["q"] = " ".join(self.q.split()).casefold()
        if self.category is not None:
            data["category"] = self.category.strip().casefold()
        for name in ("min_price", "max_price"):
            value = getattr(self, name)
            if value is not None:
                data[name] = format_amount(value.normalize())
        return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# --------------------------------------------------------------------------- sourcing views


@dataclass(frozen=True, slots=True)
class ListingView:
    """The part of a sourcing ``Listing`` the rules need. Price is the unit price range."""

    id: str
    kind: str
    title: str
    price_min: Money
    price_max: Money
    supplier_id: str
    supplier_name: str
    title_ar: str | None = None
    category: str | None = None
    condition: str | None = None
    unit: str | None = None
    trust_band: TrustBand = TrustBand.UNKNOWN
    supplier_verified: bool = False
    origin_country: str | None = None
    moq: int | None = None

    @property
    def price(self) -> Money:
        """Reference price of a listing: the minimum of its unit price range."""
        return self.price_min

    @property
    def effective_condition(self) -> str:
        return self.condition or "new"

    @property
    def effective_unit(self) -> str:
        return (self.unit or "piece").strip().casefold()


@dataclass(frozen=True, slots=True)
class SearchPage:
    items: tuple[ListingView, ...]
    total: int


@dataclass(frozen=True, slots=True)
class ListingObservation:
    """What sourcing says about a watched listing right now.

    ``listing`` is ``None`` when sourcing answered 404 (delisted / out of stock).
    ``equivalents`` is ``None`` when no equivalence search was possible (no category, or the
    search failed); the cheaper-equivalent rule is then skipped for this run.
    """

    listing: ListingView | None
    equivalents: tuple[ListingView, ...] | None = None


@dataclass(frozen=True, slots=True)
class SearchObservation:
    """First page of results for a saved search, as sourcing returns it right now."""

    page: SearchPage


Observation = ListingObservation | SearchObservation


# --------------------------------------------------------------------------- watches


@dataclass(frozen=True, slots=True)
class WatchState:
    """The evaluation state of a watch: what the service observed and what it told the owner.

    * ``baseline_price`` is the last price the owner was told about: the snapshot taken when
      the watch was created, lowered whenever an alert reports a lower price. Price drops are
      measured against it, so the same drop is never reported twice.
    * ``target_reached`` is set once the owner knows the price is at/below the target and is
      cleared when the price rises above the target again (so a new crossing alerts again).
    * ``seen_listing_ids`` (saved searches) are the results the owner already knows about.
    * ``equivalent_price`` (listing watches) is the cheapest equivalent offer already reported.
    """

    last_checked_at: datetime | None = None
    title: str | None = None
    title_ar: str | None = None
    baseline_price: Money | None = None
    baseline_listing_id: str | None = None
    baseline_at: datetime | None = None
    current_price: Money | None = None
    current_listing_id: str | None = None
    available: bool | None = None
    result_count: int | None = None
    target_reached: bool = False
    seen_listing_ids: tuple[str, ...] | None = None
    equivalent_price: Money | None = None
    equivalent_listing_id: str | None = None


STATE_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(WatchState))


@dataclass(frozen=True, slots=True)
class Watch:
    """A watched listing or saved search, owned by one user (see :class:`WatchState`)."""

    id: str
    owner_id: str
    type: WatchType
    drop_threshold_pct: Decimal
    created_at: datetime
    updated_at: datetime
    listing_id: str | None = None
    search: SearchQuery | None = None
    target_price: Money | None = None
    active: bool = True
    version: int = 1
    last_checked_at: datetime | None = None
    title: str | None = None
    title_ar: str | None = None
    baseline_price: Money | None = None
    baseline_listing_id: str | None = None
    baseline_at: datetime | None = None
    current_price: Money | None = None
    current_listing_id: str | None = None
    available: bool | None = None
    result_count: int | None = None
    target_reached: bool = False
    seen_listing_ids: tuple[str, ...] | None = None
    equivalent_price: Money | None = None
    equivalent_listing_id: str | None = None

    def state(self) -> WatchState:
        return WatchState(**{name: getattr(self, name) for name in STATE_FIELDS})

    def with_state(self, state: WatchState) -> Watch:
        return replace(self, **{name: getattr(state, name) for name in STATE_FIELDS})


def merge_seen(
    existing: Iterable[str] | None, new_ids: Iterable[str], cap: int = SEEN_IDS_CAP
) -> tuple[str, ...]:
    """Append ``new_ids`` to the remembered ids (no duplicates), keeping the newest ``cap``."""
    merged = list(existing or ())
    known = set(merged)
    for listing_id in new_ids:
        if listing_id not in known:
            merged.append(listing_id)
            known.add(listing_id)
    return tuple(merged[-cap:]) if cap > 0 else ()


# --------------------------------------------------------------------------- alerts


@dataclass(frozen=True, slots=True)
class AlertMessage:
    """Bilingual alert text: English in the base fields, Arabic in the ``_ar`` fields."""

    title: str
    title_ar: str
    body: str
    body_ar: str

    def title_for(self, locale: Locale) -> str:
        return self.title_ar if locale is Locale.AR else self.title

    def body_for(self, locale: Locale) -> str:
        return self.body_ar if locale is Locale.AR else self.body


@dataclass(frozen=True, slots=True)
class AlertPayload:
    """Structured facts behind an alert (deep links and price display in the app)."""

    listing_ids: tuple[str, ...]
    old_price: Money | None = None
    new_price: Money | None = None
    drop_pct: Decimal | None = None
    target_price: Money | None = None
    result_count: int | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"listing_ids": list(self.listing_ids)}
        if self.old_price is not None:
            data["old_price"] = self.old_price.to_json()
        if self.new_price is not None:
            data["new_price"] = self.new_price.to_json()
        if self.drop_pct is not None:
            data["drop_pct"] = format_amount(self.drop_pct)
        if self.target_price is not None:
            data["target_price"] = self.target_price.to_json()
        if self.result_count is not None:
            data["result_count"] = self.result_count
        return data

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> AlertPayload:
        def opt_money(key: str) -> Money | None:
            value = data.get(key)
            return None if value is None else Money.from_json(value)

        drop = data.get("drop_pct")
        count = data.get("result_count")
        return cls(
            listing_ids=tuple(data.get("listing_ids") or ()),
            old_price=opt_money("old_price"),
            new_price=opt_money("new_price"),
            drop_pct=None if drop is None else parse_amount(drop),
            target_price=opt_money("target_price"),
            result_count=None if count is None else int(count),
        )


@dataclass(frozen=True, slots=True)
class AlertDraft:
    """An alert a rule wants to raise, before cooldown / dedupe admission.

    ``fingerprint`` identifies the underlying event: two drafts of the same rule with the same
    fingerprint for the same watch are identical alerts. The remaining fields are *effects* on
    the watch state, applied only once the owner has been told about the event (the alert was
    created, or an identical alert already exists).
    """

    rule: RuleKind
    fingerprint: str
    message: AlertMessage
    payload: AlertPayload
    new_baseline: Money | None = None
    new_baseline_listing_id: str | None = None
    set_target_reached: bool = False
    mark_seen: tuple[str, ...] = ()
    new_equivalent: Money | None = None
    new_equivalent_listing_id: str | None = None


CandidateGroup = tuple[AlertDraft, ...]
"""Drafts about the same event, in priority order: at most one of a group becomes an alert."""


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Result of running the rules on one watch: candidate alerts + the observed state."""

    groups: tuple[CandidateGroup, ...]
    state: WatchState

    @property
    def drafts(self) -> tuple[AlertDraft, ...]:
        return tuple(draft for group in self.groups for draft in group)


@dataclass(frozen=True, slots=True)
class Alert:
    id: str
    owner_id: str
    watch_id: str
    rule: RuleKind
    message: AlertMessage
    payload: AlertPayload
    fingerprint: str
    created_at: datetime
    read: bool = False
    read_at: datetime | None = None


# --------------------------------------------------------------------------- devices


@dataclass(frozen=True, slots=True)
class Device:
    """A push-notification endpoint (FCM / APNs token) registered by an owner."""

    id: str
    owner_id: str
    platform: Platform
    locale: Locale
    token: str
    created_at: datetime
    updated_at: datetime
