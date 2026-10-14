"""USDT-TRC20 provider SKELETON. UNVERIFIED against a live chain or explorer; OFF unless
FF_PAYMENTS_PROVIDER=usdt_tron. Funds go only to the owner's own wallet (public address from the env);
no private key is ever read, stored or logged by this service.

Matching: the payer must send the exact ``pay_amount`` = invoice amount + a unique sub-cent suffix
(0.000001-0.000999 USDT) to the receiving address; the suffix identifies the invoice. Confirmed once the
transfer has ``min_confirmations`` blocks on top. Explorer shape assumed (TronGrid-like, to be verified):
  GET {base}/v1/accounts/{address}/transactions/trc20?only_to=true&contract_address=..&min_timestamp=..
      -> {"data": [{"transaction_id", "value" (integer string, 6 decimals), "block_timestamp",
                    "block_number", "token_info": {"address"}}]}
  GET {base}/v1/blocks/latest -> {"data": [{"block_number": int}]}   (assumption)
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

import httpx

from ff_payments.domain.errors import DomainError, UpstreamUnavailable
from ff_payments.providers.base import Charge, InvoiceSpec, Observation, TrackedInvoice

MICRO = Decimal("0.000001")


class ProviderNotConfigured(DomainError):
    status_code = 503
    default_code = "provider_not_configured"


def amount_with_suffix(base: Decimal, invoice_id: str, taken: frozenset[str]) -> Decimal:
    start = int(hashlib.sha256(invoice_id.encode()).hexdigest(), 16) % 999 + 1
    for i in range(999):
        cand = (base + (((start - 1 + i) % 999) + 1) * MICRO).quantize(MICRO)
        if format(cand, "f") not in taken:
            return cand
    raise ProviderNotConfigured("No free payment amount suffix; retry later", code="suffix_exhausted")


class ExplorerClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 8.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        headers = {"TRON-PRO-API-KEY": api_key} if api_key else {}
        self._c = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, headers=headers,
                                    transport=transport)

    async def incoming_trc20(self, address: str, contract: str, since_ms: int) -> list[dict]:
        try:
            r = await self._c.get(f"/v1/accounts/{address}/transactions/trc20", params={
                "only_to": "true", "contract_address": contract, "min_timestamp": since_ms, "limit": 200})
            r.raise_for_status()
            return list(r.json()["data"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise UpstreamUnavailable("Chain explorer unavailable") from exc

    async def latest_block(self) -> int:
        try:
            r = await self._c.get("/v1/blocks/latest")
            r.raise_for_status()
            return int(r.json()["data"][0]["block_number"])
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
            raise UpstreamUnavailable("Chain explorer unavailable") from exc

    async def aclose(self) -> None:
        await self._c.aclose()


class UsdtTronProvider:
    name = "usdt_tron"

    def __init__(self, *, address: str | None, contract: str | None, explorer: ExplorerClient | None,
                 min_confirmations: int = 20) -> None:
        self.address, self.contract, self.explorer = address, contract, explorer
        self.min_confirmations = min_confirmations

    async def create(self, spec: InvoiceSpec) -> Charge:
        if not (self.address and self.contract and self.explorer):
            raise ProviderNotConfigured("usdt_tron needs FF_PAYMENTS_USDT_RECEIVE_ADDRESS, _CONTRACT and _EXPLORER_URL")
        if spec.currency not in ("USD", "USDT"):
            raise DomainError("usdt_tron invoices must be in USD or USDT", code="unsupported_currency")
        pay = amount_with_suffix(spec.amount, spec.invoice_id, spec.taken_pay_amounts)
        return Charge(provider_ref=spec.memo, pay_address=self.address, pay_url=None,
                      pay_amount=pay, pay_currency="USDT")

    async def poll(self, inv: TrackedInvoice) -> Observation | None:
        if not (self.address and self.contract and self.explorer and inv.pay_amount is not None):
            return None
        txs = await self.explorer.incoming_trc20(self.address, self.contract, inv.created_ts_ms)
        for tx in txs:
            info = tx.get("token_info") or {}
            if info.get("address") not in (None, self.contract):
                continue
            try:
                value = Decimal(str(tx["value"])) * MICRO
            except (KeyError, ArithmeticError):
                continue
            if value != inv.pay_amount:
                continue
            latest = await self.explorer.latest_block()
            conf = max(0, latest - int(tx.get("block_number", latest)) + 1)
            return Observation("paid" if conf >= self.min_confirmations else "confirming",
                               str(tx.get("transaction_id")), conf)
        return None
