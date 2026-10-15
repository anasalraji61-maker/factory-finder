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
import time
from decimal import Decimal

import httpx

from ff_payments.domain.errors import DomainError, UpstreamUnavailable
from ff_payments.providers.base import Charge, InvoiceSpec, Observation, TrackedInvoice

MICRO = Decimal("0.000001")
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_TRON_VERSION = 0x41


def is_valid_tron_address(addr: object) -> bool:
    """Base58Check: 34 chars, leading 'T', 25 decoded bytes = 0x41 + 20-byte hash + 4-byte double-SHA256 checksum."""
    if not isinstance(addr, str) or len(addr) != 34 or addr[0] != "T" or any(c not in _B58 for c in addr):
        return False
    n = 0
    for c in addr:
        n = n * 58 + _B58.index(c)
    try:
        raw = n.to_bytes(25, "big")
    except OverflowError:
        return False
    return raw[0] == _TRON_VERSION and hashlib.sha256(hashlib.sha256(raw[:21]).digest()).digest()[:4] == raw[21:]


def parse_micro(value: object) -> Decimal | None:
    """Explorer ``value`` is an integer string of 6-decimal units. Floats, exponents, fractions, negatives -> None."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value)
    if not text.isascii() or not text.isdigit():
        return None
    return Decimal(int(text)).scaleb(-6).quantize(MICRO)


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
        self._cooldown_until = 0.0  # monotonic; set after 429/503 so a sweep never hammers a throttling explorer

    def _check_cooldown(self) -> None:
        if time.monotonic() < self._cooldown_until:
            raise UpstreamUnavailable("Chain explorer rate-limited; backing off")

    def _note_throttle(self, r: httpx.Response) -> None:
        if r.status_code in (429, 503):
            try:
                wait = float(r.headers.get("Retry-After", ""))
            except ValueError:
                wait = 30.0
            self._cooldown_until = time.monotonic() + min(max(wait, 1.0), 300.0)

    async def incoming_trc20(self, address: str, contract: str, since_ms: int) -> list[dict]:
        self._check_cooldown()
        try:
            r = await self._c.get(f"/v1/accounts/{address}/transactions/trc20", params={
                "only_to": "true", "contract_address": contract, "min_timestamp": since_ms, "limit": 200})
            self._note_throttle(r)
            r.raise_for_status()
            data = r.json()["data"]
            if not isinstance(data, list):
                raise ValueError("data is not a list")
            return data
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            raise UpstreamUnavailable("Chain explorer unavailable") from exc

    async def latest_block(self) -> int:
        self._check_cooldown()
        try:
            r = await self._c.get("/v1/blocks/latest")
            self._note_throttle(r)
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
        self.min_confirmations = max(1, min_confirmations)

    async def create(self, spec: InvoiceSpec) -> Charge:
        if not (self.address and self.contract and self.explorer):
            raise ProviderNotConfigured("usdt_tron needs FF_PAYMENTS_USDT_RECEIVE_ADDRESS, _CONTRACT and _EXPLORER_URL")
        if not is_valid_tron_address(self.address) or not is_valid_tron_address(self.contract):
            raise ProviderNotConfigured("usdt_tron receive address / contract is not a valid TRON address",
                                        code="invalid_address")
        if spec.currency not in ("USD", "USDT"):
            raise DomainError("usdt_tron invoices must be in USD or USDT", code="unsupported_currency")
        pay = amount_with_suffix(spec.amount, spec.invoice_id, spec.taken_pay_amounts)
        return Charge(provider_ref=spec.memo, pay_address=self.address, pay_url=None,
                      pay_amount=pay, pay_currency="USDT")

    async def poll(self, inv: TrackedInvoice) -> Observation | None:
        if not (self.address and self.contract and self.explorer and inv.pay_amount is not None):
            return None
        if inv.pay_address and inv.pay_address != self.address:  # address was rotated: never match old invoices
            return None
        txs = await self.explorer.incoming_trc20(self.address, self.contract, inv.created_ts_ms)
        best: tuple[dict, int] | None = None
        for tx in txs:
            if not isinstance(tx, dict):
                continue
            if (tx.get("token_info") or {}).get("address") != self.contract:
                continue
            if tx.get("to") not in (None, self.address):
                continue
            value = parse_micro(tx.get("value"))
            if value is None or value != inv.pay_amount:  # exact match only: under/overpay never settles
                continue
            ts = tx.get("block_timestamp")
            if not isinstance(ts, int) or ts < inv.created_ts_ms:  # older transfer cannot belong to this invoice
                continue
            blk = tx.get("block_number")
            height = blk if isinstance(blk, int) and not isinstance(blk, bool) and blk > 0 else None
            if not tx.get("transaction_id"):
                continue
            h = height or 0
            if best is None or (h and (best[1] == 0 or h < best[1])):
                best = (tx, h)  # duplicates of the same amount: the earliest mined block wins
        if best is None:
            return None
        tx, height = best
        conf = 0
        if height:
            conf = max(0, await self.explorer.latest_block() - height + 1)
        return Observation("paid" if conf >= self.min_confirmations else "confirming",
                           str(tx["transaction_id"]), conf)
