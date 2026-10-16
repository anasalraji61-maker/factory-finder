"""Request models (strict: money is a decimal string, never a JSON number)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator

from ff_payments.domain.enums import InvoiceKind, ListingKind

MAX_AMOUNT = Decimal("999999999999")


class Money(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: StrictStr = Field(pattern=r"^[0-9]{1,12}(\.[0-9]{1,6})?$")
    currency: StrictStr = Field(pattern=r"^[A-Z]{3,5}$")

    @field_validator("amount")
    @classmethod
    def _positive(cls, v: str) -> str:
        try:
            d = Decimal(v)
        except InvalidOperation as exc:  # pragma: no cover - regex already guards
            raise ValueError("invalid amount") from exc
        if d <= 0:
            raise ValueError("amount must be > 0")
        return v

    @property
    def value(self) -> Decimal:
        return Decimal(self.amount)


class CommissionBasis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subtotal: Money
    listing_kind: ListingKind


class InvoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deal_id: str = Field(min_length=1, max_length=64)
    kind: InvoiceKind
    memo: str | None = Field(default=None, max_length=200)
    # admin-only overrides
    payer_user_id: str | None = Field(default=None, max_length=64)
    payee: str | None = Field(default=None, max_length=64)
    amount: Money | None = None
    commission_basis: CommissionBasis | None = None
    expires_in_minutes: StrictInt | None = Field(default=None, ge=1, le=10080)

    @property
    def has_overrides(self) -> bool:
        return any(x is not None for x in (self.payer_user_id, self.payee, self.amount,
                                           self.commission_basis, self.expires_in_minutes))


class WebhookEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    event_id: str = Field(min_length=1, max_length=128)
    type: Literal["payment.confirming", "payment.confirmed", "payment.failed", "payment.expired"]
    invoice_id: str | None = Field(default=None, max_length=64)
    provider_ref: str | None = Field(default=None, max_length=128)
    tx_ref: str | None = Field(default=None, max_length=128)
    confirmations: StrictInt | None = Field(default=None, ge=0)
    amount: Money | None = None


class ReviewResolve(BaseModel):
    """Admin resolution of one invoice in the review queue."""

    model_config = ConfigDict(extra="forbid")
    action: Literal["settle", "refund_flag", "dismiss"]
    note: StrictStr | None = Field(default=None, max_length=500)
    confirm_amount_mismatch: StrictBool = False
    received_amount: Money | None = None  # amount_mismatch settle only: what actually arrived

    @field_validator("note")
    @classmethod
    def _clean_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in v):
            raise ValueError("note contains control characters")
        return v or None
