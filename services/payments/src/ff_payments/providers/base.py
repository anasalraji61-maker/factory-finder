"""PaymentProvider protocol (pure types). Providers never touch the database."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class InvoiceSpec:
    invoice_id: str
    memo: str
    amount: Decimal
    currency: str
    taken_pay_amounts: frozenset[str] = frozenset()  # open invoices' pay_amount values (suffix uniqueness)


@dataclass(frozen=True, slots=True)
class Charge:
    provider_ref: str
    pay_address: str | None = None
    pay_url: str | None = None
    pay_amount: Decimal | None = None
    pay_currency: str | None = None


@dataclass(frozen=True, slots=True)
class Observation:
    """What the provider saw on its side for one invoice."""

    status: str  # confirming | paid
    tx_ref: str | None = None
    confirmations: int = 0


@dataclass(frozen=True, slots=True)
class TrackedInvoice:
    provider_ref: str | None
    memo: str
    pay_address: str | None
    pay_amount: Decimal | None
    created_ts_ms: int


class PaymentProvider(Protocol):
    name: str

    async def create(self, spec: InvoiceSpec) -> Charge: ...

    async def poll(self, inv: TrackedInvoice) -> Observation | None: ...
