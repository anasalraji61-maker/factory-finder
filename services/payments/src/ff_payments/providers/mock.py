"""Deterministic provider for tests/dev: create -> awaiting; ``confirm()`` is the test hook."""

from __future__ import annotations

from ff_payments.providers.base import Charge, InvoiceSpec, Observation, TrackedInvoice


class MockProvider:
    name = "mock"

    def __init__(self) -> None:
        self._seen: dict[str, Observation] = {}

    async def create(self, spec: InvoiceSpec) -> Charge:
        return Charge(
            provider_ref=f"mock_{spec.invoice_id}", pay_address=f"mock-address-{spec.invoice_id}",
            pay_url=f"https://pay.invalid/mock/{spec.invoice_id}", pay_amount=spec.amount,
            pay_currency=spec.currency,
        )

    # test hooks ----------------------------------------------------------------------------
    def confirm(self, provider_ref: str, *, tx_ref: str = "mock_tx", confirmations: int = 1) -> None:
        self._seen[provider_ref] = Observation("paid", tx_ref, confirmations)

    def seen(self, provider_ref: str, *, tx_ref: str = "mock_tx", confirmations: int = 0) -> None:
        self._seen[provider_ref] = Observation("confirming", tx_ref, confirmations)

    async def poll(self, inv: TrackedInvoice) -> Observation | None:
        return self._seen.get(inv.provider_ref or "")
