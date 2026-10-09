"""Alert admission: cooldown per (watch, rule), dedupe of identical alerts, state effects.

Pure logic. For each candidate group the first draft that is neither a duplicate nor cooling
down becomes an alert; an identical alert (same watch, rule and fingerprint) means the owner
already knows, so the draft's effects are applied without creating anything new.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from ff_notifications.domain.models import AlertDraft, Evaluation, RuleKind, WatchState, merge_seen

DEFAULT_COOLDOWN = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class CooldownPolicy:
    """Minimum interval between two alerts of the same rule for the same watch."""

    default: timedelta = DEFAULT_COOLDOWN
    per_rule: Mapping[RuleKind, timedelta] | None = None

    def for_rule(self, rule: RuleKind) -> timedelta:
        if self.per_rule and rule in self.per_rule:
            return self.per_rule[rule]
        return self.default

    def in_cooldown(self, rule: RuleKind, last_alert_at: datetime | None, now: datetime) -> bool:
        if last_alert_at is None:
            return False
        window = self.for_rule(rule)
        return window > timedelta(0) and now - last_alert_at < window


@dataclass(frozen=True, slots=True)
class AlertHistory:
    """What the store knows about previous alerts of one watch.

    ``last_alert_at``: creation time of the latest alert per rule.
    ``fingerprints``: (rule, fingerprint) of every alert raised for the watch.
    """

    last_alert_at: Mapping[RuleKind, datetime]
    fingerprints: frozenset[tuple[RuleKind, str]]

    @classmethod
    def empty(cls) -> AlertHistory:
        return cls(last_alert_at={}, fingerprints=frozenset())

    def is_duplicate(self, draft: AlertDraft) -> bool:
        return (draft.rule, draft.fingerprint) in self.fingerprints


@dataclass(frozen=True, slots=True)
class SkippedDraft:
    rule: RuleKind
    reason: str  # "duplicate" | "cooldown"


@dataclass(frozen=True, slots=True)
class Decision:
    to_create: tuple[AlertDraft, ...]
    skipped: tuple[SkippedDraft, ...]
    state: WatchState


def apply_effects(state: WatchState, draft: AlertDraft, now: datetime) -> WatchState:
    """State after the owner has been told about ``draft``'s event."""
    if draft.new_baseline is not None:
        state = replace(
            state,
            baseline_price=draft.new_baseline,
            baseline_listing_id=draft.new_baseline_listing_id,
            baseline_at=now,
        )
    if draft.set_target_reached:
        state = replace(state, target_reached=True)
    if draft.mark_seen:
        state = replace(state, seen_listing_ids=merge_seen(state.seen_listing_ids, draft.mark_seen))
    if draft.new_equivalent is not None:
        state = replace(
            state,
            equivalent_price=draft.new_equivalent,
            equivalent_listing_id=draft.new_equivalent_listing_id,
        )
    return state


def decide(
    evaluation: Evaluation,
    history: AlertHistory,
    now: datetime,
    cooldown: CooldownPolicy,
) -> Decision:
    """Choose which drafts become alerts and compute the watch state to persist."""
    state = evaluation.state
    to_create: list[AlertDraft] = []
    skipped: list[SkippedDraft] = []
    for group in evaluation.groups:
        for draft in group:
            if history.is_duplicate(draft):
                skipped.append(SkippedDraft(draft.rule, "duplicate"))
                state = apply_effects(state, draft, now)
                break
            if cooldown.in_cooldown(draft.rule, history.last_alert_at.get(draft.rule), now):
                skipped.append(SkippedDraft(draft.rule, "cooldown"))
                continue
            to_create.append(draft)
            state = apply_effects(state, draft, now)
            break
    return Decision(to_create=tuple(to_create), skipped=tuple(skipped), state=state)
