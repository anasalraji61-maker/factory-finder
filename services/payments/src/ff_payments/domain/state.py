"""Invoice status machine (pure). Terminal: expired, failed, refunded."""

from __future__ import annotations

from ff_payments.domain.enums import InvoiceStatus as S
from ff_payments.domain.errors import InvalidTransition

TRANSITIONS: dict[S, frozenset[S]] = {
    S.PENDING: frozenset({S.AWAITING_PAYMENT, S.FAILED, S.EXPIRED}),
    S.AWAITING_PAYMENT: frozenset({S.CONFIRMING, S.PAID, S.EXPIRED, S.FAILED}),
    S.CONFIRMING: frozenset({S.PAID, S.FAILED, S.AWAITING_PAYMENT}),  # back: chain reorg
    S.PAID: frozenset({S.REFUNDED}),
    S.EXPIRED: frozenset(),
    S.FAILED: frozenset(),
    S.REFUNDED: frozenset(),
}
OPEN = frozenset({S.PENDING, S.AWAITING_PAYMENT, S.CONFIRMING})
CANCELLABLE = frozenset({S.PENDING, S.AWAITING_PAYMENT})


def can(current: S, target: S) -> bool:
    return target in TRANSITIONS[current]


def require(current: S, target: S, invoice_id: str | None = None) -> None:
    if not can(current, target):
        raise InvalidTransition("invoice", current, target.value,
                                allowed=[t.value for t in TRANSITIONS[current]], entity_id=invoice_id)
