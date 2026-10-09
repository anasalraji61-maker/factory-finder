"""The rules engine: turns (watch, fresh observation) into candidate alerts and a new state.

Pure functions only. Each evaluation yields up to two *groups* of drafts about the same event,
in priority order; the policy turns at most one draft of a group into an alert, falling
through to the next draft when a rule is cooling down.

Listing watches

* offer group, priority ``below_target`` > ``price_drop`` > ``back_in_stock``

  - ``below_target``: price <= target (same currency) and the owner has not been told yet;
    re-arms when the price goes back above the target.
  - ``price_drop``: price fell at least ``drop_threshold_pct`` % below the baseline, i.e. the
    last price the owner was told about (creation snapshot, then each reported price).
  - ``back_in_stock``: the listing was seen, then disappeared (sourcing 404), and is back.

* equivalent group: ``cheaper_equivalent`` - another supplier offers the same kind, category,
  condition and unit in the same currency, strictly cheaper, with a trust band that is not
  red, and cheaper than any equivalent already reported for this watch.

Saved searches (results whose trust band is red are ignored)

* offer group, priority ``below_target`` > ``price_drop`` > ``back_in_stock``: the price rules
  applied to the best (cheapest) result; ``back_in_stock`` when results reappear after a check
  that found none.
* results group: ``new_results`` - listings the owner has not seen yet. Listings the offer
  group reports in the same check are excluded, so one listing never yields two alerts.

State effects (baseline, target reached, seen ids, reported equivalent) live on the drafts and
are applied by :func:`ff_notifications.domain.policy.decide` only once the owner has been told
(the alert is created, or an identical alert already exists). An event suppressed by a
cooldown therefore stays pending and is reported when the cooldown is over.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from ff_notifications.domain import messages
from ff_notifications.domain.models import (
    AlertDraft,
    AlertMessage,
    AlertPayload,
    CandidateGroup,
    Evaluation,
    ListingObservation,
    ListingView,
    Observation,
    RuleKind,
    SearchObservation,
    SearchQuery,
    TrustBand,
    Watch,
    WatchState,
    WatchType,
    merge_seen,
)
from ff_notifications.domain.money import Money, canonical_amount, drop_percent, dropped_at_least

PAYLOAD_IDS_CAP = 50
"""Maximum number of listing ids carried in one alert payload."""


@dataclass(frozen=True, slots=True)
class RuleConfig:
    """Tunables of the rules engine.

    ``equivalent_min_saving_pct``: minimum saving (in %) of an equivalent offer versus the
    watched listing before it is reported; ``0`` means any strictly lower price.
    """

    equivalent_min_saving_pct: Decimal = Decimal(0)


DEFAULT_RULES = RuleConfig()


class ObservationMismatchError(TypeError):
    """The observation kind does not match the watch type."""


def evaluate(
    watch: Watch,
    observation: Observation,
    now: datetime,
    config: RuleConfig = DEFAULT_RULES,
) -> Evaluation:
    """Run every applicable rule for ``watch`` against a fresh ``observation``."""
    if watch.type is WatchType.LISTING:
        if not isinstance(observation, ListingObservation):
            raise ObservationMismatchError("a listing watch needs a ListingObservation")
        return _evaluate_listing(watch, observation, now, config)
    if not isinstance(observation, SearchObservation):
        raise ObservationMismatchError("a search watch needs a SearchObservation")
    if watch.search is None:
        raise ObservationMismatchError("a search watch needs a saved search")
    return _evaluate_search(watch, watch.search, observation, now)


# --------------------------------------------------------------------------- helpers


def price_key(listing: ListingView) -> tuple[Decimal, int, str]:
    """Deterministic "cheapest first" ordering: price, then trust band, then id."""
    return (listing.price.amount, listing.trust_band.rank, listing.id)


def money_key(money: Money) -> str:
    return f"{canonical_amount(money.amount)}{money.currency}"


def ids_digest(ids: Iterable[str]) -> str:
    joined = "\n".join(sorted(ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]


def _norm(text: str | None) -> str | None:
    return None if text is None else " ".join(text.split()).casefold()


def equivalence_query(listing: ListingView) -> SearchQuery | None:
    """Sourcing search used to look for equivalents of ``listing`` (``None``: impossible).

    ``max_price`` only narrows what sourcing returns; candidates are always re-checked by
    :func:`is_equivalent`, so another reading of that filter by sourcing can hide offers but
    never produce a wrong alert.
    """
    if not listing.category:
        return None
    condition = listing.condition if listing.condition in ("new", "used") else None
    return SearchQuery(
        kind=listing.kind,
        category=listing.category,
        condition=condition,
        max_price=listing.price.amount,
    )


def is_equivalent(watched: ListingView, candidate: ListingView) -> bool:
    """Same kind of goods from a different supplier, priced in a comparable way."""
    return (
        candidate.id != watched.id
        and candidate.supplier_id != watched.supplier_id
        and candidate.kind == watched.kind
        and watched.category is not None
        and _norm(candidate.category) == _norm(watched.category)
        and candidate.effective_condition == watched.effective_condition
        and candidate.effective_unit == watched.effective_unit
        and candidate.price.currency == watched.price.currency
    )


def find_cheaper_equivalent(
    watched: ListingView,
    candidates: Iterable[ListingView],
    already_reported: Money | None = None,
    min_saving_pct: Decimal = Decimal(0),
) -> ListingView | None:
    """Cheapest equivalent offer worth reporting, if any."""
    best: ListingView | None = None
    for candidate in candidates:
        if not is_equivalent(watched, candidate) or candidate.trust_band is TrustBand.RED:
            continue
        if not candidate.price < watched.price:
            continue
        if min_saving_pct > 0 and not dropped_at_least(
            watched.price.amount, candidate.price.amount, min_saving_pct
        ):
            continue
        if (
            already_reported is not None
            and already_reported.same_currency(candidate.price)
            and not candidate.price < already_reported
        ):
            continue
        if best is None or price_key(candidate) < price_key(best):
            best = candidate
    return best


def target_check(target: Money | None, price: Money, reached: bool) -> tuple[bool, bool]:
    """Return (raise ``below_target``?, new ``target_reached`` flag) for an observed price."""
    if target is None or not target.same_currency(price):
        return False, reached
    if price <= target:
        return not reached, reached
    return False, False


def is_target_met(target: Money | None, price: Money | None) -> bool:
    """True when a known price is at or below the target (same currency, no FX)."""
    return (
        target is not None
        and price is not None
        and target.same_currency(price)
        and price <= target
    )


def reference_currency(
    eligible: Sequence[ListingView],
    target: Money | None = None,
    baseline: Money | None = None,
) -> str | None:
    """Currency in which a saved search compares prices (no FX conversion in v1).

    Preference: the target's currency, then the baseline's, then the most common currency
    among the results (ties broken alphabetically).
    """
    counts = Counter(item.price.currency for item in eligible)
    if not counts:
        return None
    for preferred in (target, baseline):
        if preferred is not None and preferred.currency in counts:
            return preferred.currency
    return min(counts, key=lambda code: (-counts[code], code))


def best_offer(
    items: Iterable[ListingView],
    target: Money | None = None,
    baseline: Money | None = None,
) -> ListingView | None:
    """Cheapest non-red result in the reference currency (the saved search's "best result")."""
    eligible = [item for item in items if item.trust_band is not TrustBand.RED]
    currency = reference_currency(eligible, target, baseline)
    priced = [item for item in eligible if item.price.currency == currency]
    return min(priced, key=price_key) if priced else None


@dataclass(frozen=True, slots=True)
class _PriceFacts:
    """Price-rule inputs for the watched offer (listing, or best search result)."""

    baseline: Money | None
    drop_pct: Decimal | None
    raise_target: bool
    state: WatchState


def _price_facts(watch: Watch, state: WatchState, item: ListingView, now: datetime) -> _PriceFacts:
    current = item.price
    baseline = watch.baseline_price
    if baseline is None or not baseline.same_currency(current):
        # First snapshot (or the currency changed): start the baseline silently; a drop can
        # only be measured from the next check on.
        state = replace(
            state, baseline_price=current, baseline_listing_id=item.id, baseline_at=now
        )
        baseline = None
    raise_target, reached = target_check(watch.target_price, current, watch.target_reached)
    state = replace(state, target_reached=reached)
    drop_pct = None
    if baseline is not None and dropped_at_least(
        baseline.amount, current.amount, watch.drop_threshold_pct
    ):
        drop_pct = drop_percent(baseline.amount, current.amount)
    return _PriceFacts(baseline, drop_pct, raise_target, state)


def _offer_draft(
    rule: RuleKind,
    fingerprint: str,
    message: AlertMessage,
    payload: AlertPayload,
    item: ListingView | None,
    *,
    set_target_reached: bool = False,
    mark_seen: tuple[str, ...] = (),
) -> AlertDraft:
    """Draft whose delivery re-bases the watch on the reported offer's price."""
    return AlertDraft(
        rule=rule,
        fingerprint=fingerprint,
        message=message,
        payload=payload,
        new_baseline=item.price if item else None,
        new_baseline_listing_id=item.id if item else None,
        set_target_reached=set_target_reached,
        mark_seen=mark_seen,
    )


# --------------------------------------------------------------------------- listing watches


def _evaluate_listing(
    watch: Watch, obs: ListingObservation, now: datetime, config: RuleConfig
) -> Evaluation:
    state = replace(watch.state(), last_checked_at=now)
    listing = obs.listing
    if listing is None:
        # Delisted / out of stock. Only a listing that was seen can come "back in stock".
        return Evaluation(
            groups=(), state=replace(state, available=False if watch.available else None)
        )

    current = listing.price
    state = replace(
        state,
        title=listing.title,
        title_ar=listing.title_ar,
        current_price=current,
        current_listing_id=listing.id,
        available=True,
    )
    facts = _price_facts(watch, state, listing, now)
    state = facts.state
    target = watch.target_price

    offer: list[AlertDraft] = []
    if facts.raise_target and target is not None:
        offer.append(
            _offer_draft(
                RuleKind.BELOW_TARGET,
                f"{listing.id}:{money_key(current)}:{money_key(target)}",
                messages.below_target_listing(listing, current, target),
                AlertPayload(
                    listing_ids=(listing.id,),
                    old_price=facts.baseline,
                    new_price=current,
                    drop_pct=facts.drop_pct,
                    target_price=target,
                ),
                listing,
                set_target_reached=True,
            )
        )
    if facts.drop_pct is not None and facts.baseline is not None:
        offer.append(
            _offer_draft(
                RuleKind.PRICE_DROP,
                f"{listing.id}:{money_key(current)}",
                messages.price_drop_listing(listing, facts.baseline, current, facts.drop_pct),
                AlertPayload(
                    listing_ids=(listing.id,),
                    old_price=facts.baseline,
                    new_price=current,
                    drop_pct=facts.drop_pct,
                    target_price=target,
                ),
                listing,
            )
        )
    if watch.available is False:
        offer.append(
            _offer_draft(
                RuleKind.BACK_IN_STOCK,
                f"{listing.id}:{money_key(current)}",
                messages.back_in_stock_listing(listing),
                AlertPayload(
                    listing_ids=(listing.id,),
                    old_price=watch.current_price,
                    new_price=current,
                ),
                listing,
            )
        )

    groups: list[CandidateGroup] = []
    if offer:
        groups.append(tuple(offer))

    if obs.equivalents is not None:
        alternative = find_cheaper_equivalent(
            listing, obs.equivalents, watch.equivalent_price, config.equivalent_min_saving_pct
        )
        if alternative is not None:
            saving = drop_percent(current.amount, alternative.price.amount)
            groups.append(
                (
                    AlertDraft(
                        rule=RuleKind.CHEAPER_EQUIVALENT,
                        fingerprint=f"{alternative.id}:{money_key(alternative.price)}",
                        message=messages.cheaper_equivalent(listing, alternative, saving),
                        payload=AlertPayload(
                            listing_ids=(listing.id, alternative.id),
                            old_price=current,
                            new_price=alternative.price,
                            drop_pct=saving,
                        ),
                        new_equivalent=alternative.price,
                        new_equivalent_listing_id=alternative.id,
                    ),
                )
            )
    return Evaluation(groups=tuple(groups), state=state)


# --------------------------------------------------------------------------- saved searches


def _evaluate_search(
    watch: Watch, query: SearchQuery, obs: SearchObservation, now: datetime
) -> Evaluation:
    page = obs.page
    eligible = [item for item in page.items if item.trust_band is not TrustBand.RED]
    total = max(page.total, len(page.items))
    best = best_offer(eligible, watch.target_price, watch.baseline_price)

    if eligible:
        available: bool | None = True
    else:
        # "Back in stock" needs results that were seen before and then vanished.
        available = False if watch.available else watch.available
    state = replace(
        watch.state(),
        last_checked_at=now,
        result_count=total,
        available=available,
        current_price=best.price if best else None,
        current_listing_id=best.id if best else None,
    )

    first_snapshot = watch.seen_listing_ids is None
    seen = set(watch.seen_listing_ids or ())
    target = watch.target_price
    groups: list[CandidateGroup] = []

    # ---- offer group: the best result
    offer: list[AlertDraft] = []
    if best is not None:
        facts = _price_facts(watch, state, best, now)
        state = facts.state
        mark_best = () if first_snapshot or best.id in seen else (best.id,)
        if facts.raise_target and target is not None:
            offer.append(
                _offer_draft(
                    RuleKind.BELOW_TARGET,
                    f"{best.id}:{money_key(best.price)}:{money_key(target)}",
                    messages.below_target_search(query, best, best.price, target),
                    AlertPayload(
                        listing_ids=(best.id,),
                        old_price=facts.baseline,
                        new_price=best.price,
                        drop_pct=facts.drop_pct,
                        target_price=target,
                        result_count=total,
                    ),
                    best,
                    set_target_reached=True,
                    mark_seen=mark_best,
                )
            )
        if facts.drop_pct is not None and facts.baseline is not None:
            offer.append(
                _offer_draft(
                    RuleKind.PRICE_DROP,
                    f"{best.id}:{money_key(best.price)}",
                    messages.price_drop_search(
                        query, best, facts.baseline, best.price, facts.drop_pct
                    ),
                    AlertPayload(
                        listing_ids=(best.id,),
                        old_price=facts.baseline,
                        new_price=best.price,
                        drop_pct=facts.drop_pct,
                        target_price=target,
                        result_count=total,
                    ),
                    best,
                    mark_seen=mark_best,
                )
            )
    back_in_stock = watch.available is False and bool(eligible) and not first_snapshot
    if back_in_stock:
        offer.append(
            _offer_draft(
                RuleKind.BACK_IN_STOCK,
                f"results:{ids_digest(item.id for item in eligible)}",
                messages.back_in_stock_search(query, total, best.price if best else None),
                AlertPayload(
                    listing_ids=tuple(item.id for item in eligible[:PAYLOAD_IDS_CAP]),
                    new_price=best.price if best else None,
                    result_count=total,
                ),
                best,
                mark_seen=tuple(item.id for item in eligible if item.id not in seen),
            )
        )
    if offer:
        groups.append(tuple(offer))

    # ---- results group: listings the owner has not seen yet
    if first_snapshot:
        # Creation could not snapshot the results: start from what is there now, silently.
        state = replace(state, seen_listing_ids=merge_seen((), (i.id for i in eligible)))
        return Evaluation(groups=tuple(groups), state=state)

    if back_in_stock:
        covered = {item.id for item in eligible}
    elif offer and best is not None:
        covered = {best.id}
    else:
        covered = set()
    fresh = [item for item in eligible if item.id not in seen and item.id not in covered]
    if fresh:
        fresh_ids = tuple(item.id for item in fresh)
        currency = best.price.currency if best else None
        comparable = [item for item in fresh if item.price.currency == currency]
        highlight = min(comparable, key=price_key) if comparable else fresh[0]
        groups.append(
            (
                AlertDraft(
                    rule=RuleKind.NEW_RESULTS,
                    fingerprint=f"new:{ids_digest(fresh_ids)}",
                    message=messages.new_results(
                        query, len(fresh), highlight, highlight_is_cheapest=bool(comparable)
                    ),
                    payload=AlertPayload(
                        listing_ids=fresh_ids[:PAYLOAD_IDS_CAP],
                        new_price=highlight.price,
                        result_count=len(fresh),
                    ),
                    mark_seen=fresh_ids,
                ),
            )
        )
    return Evaluation(groups=tuple(groups), state=state)
