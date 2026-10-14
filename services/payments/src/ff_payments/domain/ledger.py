"""Double-entry helpers (pure). A group of legs must have equal debit and credit totals per currency."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from ff_payments.domain.enums import Direction
from ff_payments.domain.errors import DomainError


class LedgerImbalance(DomainError):
    status_code = 500
    default_code = "ledger_imbalance"


@dataclass(frozen=True, slots=True)
class Leg:
    account: str
    direction: Direction
    amount: Decimal
    currency: str


def check_balanced(legs: list[Leg]) -> None:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for leg in legs:
        if leg.amount <= 0:
            raise LedgerImbalance("Ledger legs must be positive")
        totals[leg.currency] += leg.amount if leg.direction == Direction.DEBIT else -leg.amount
    if not legs or any(v != 0 for v in totals.values()):
        raise LedgerImbalance("Ledger group is not balanced")


def payment_legs(*, provider: str, payee: str, kind: str, amount: Decimal, currency: str) -> list[Leg]:
    credit = "revenue:commission" if kind == "commission" else f"payable:{payee}"
    return [Leg(f"clearing:{provider}", Direction.DEBIT, amount, currency),
            Leg(credit, Direction.CREDIT, amount, currency)]


def refund_legs(legs: list[Leg]) -> list[Leg]:
    flip = {Direction.DEBIT: Direction.CREDIT, Direction.CREDIT: Direction.DEBIT}
    return [Leg(x.account, flip[x.direction], x.amount, x.currency) for x in legs]
