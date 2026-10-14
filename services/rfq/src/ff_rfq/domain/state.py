"""State machines for requests and offers (pure)."""

from __future__ import annotations

from ff_rfq.domain.enums import DealStatus as D
from ff_rfq.domain.enums import OfferStatus as O
from ff_rfq.domain.enums import RequestStatus as R
from ff_rfq.domain.errors import InvalidTransition

# action -> (allowed source statuses, target status)
REQUEST_ACTIONS: dict[str, tuple[frozenset[R], R]] = {
    "receive_offer": (frozenset({R.OPEN, R.NEGOTIATING}), R.NEGOTIATING),
    "release": (frozenset({R.NEGOTIATING}), R.OPEN),  # last active offer gone
    "award": (frozenset({R.OPEN, R.NEGOTIATING}), R.AWARDED),
    "close": (frozenset({R.OPEN, R.NEGOTIATING}), R.CLOSED),
    "expire": (frozenset({R.OPEN, R.NEGOTIATING}), R.EXPIRED),
}
OFFER_ACTIONS: dict[str, tuple[frozenset[O], O]] = {
    "withdraw": (frozenset({O.ACTIVE}), O.WITHDRAWN),
    "reject": (frozenset({O.ACTIVE}), O.REJECTED),
    "accept": (frozenset({O.ACTIVE}), O.ACCEPTED),
    "expire": (frozenset({O.ACTIVE}), O.EXPIRED),
}

DEAL_ACTIONS: dict[str, tuple[frozenset[D], D]] = {
    "mark_paid": (frozenset({D.PENDING_PAYMENT}), D.PAID),  # all existing invoices settled
    "start_fulfilment": (frozenset({D.PAID}), D.IN_FULFILMENT),
    "confirm_receipt": (frozenset({D.IN_FULFILMENT}), D.COMPLETED),
    "reopen_payment": (frozenset({D.PAID}), D.PENDING_PAYMENT),  # commission refunded before fulfilment
    "refund": (frozenset({D.PENDING_PAYMENT, D.PAID}), D.REFUNDED),  # deal_payment refunded before fulfilment
    "dispute": (frozenset({D.IN_FULFILMENT}), D.DISPUTED),  # refund after fulfilment began: human decides
}


def _apply(entity: str, table: dict, current, action: str, entity_id: str | None):
    allowed_from, target = table[action]
    if current not in allowed_from:
        allowed = [a for a, (src, _) in table.items() if current in src]
        raise InvalidTransition(entity, current, action, allowed=allowed, entity_id=entity_id)
    return target


def request_transition(current: R, action: str, entity_id: str | None = None) -> R:
    return _apply("request", REQUEST_ACTIONS, current, action, entity_id)


def offer_transition(current: O, action: str, entity_id: str | None = None) -> O:
    return _apply("offer", OFFER_ACTIONS, current, action, entity_id)


def deal_transition(current: D, action: str, entity_id: str | None = None) -> D:
    return _apply("deal", DEAL_ACTIONS, current, action, entity_id)
