# payments: USDT-TRC20 provider QA (2026-10)

Scope: `services/payments` (`providers/usdt_tron.py`, `providers/mock.py`, sweep/ledger/commission). All tests offline (canned TronGrid-like JSON through `httpx.MockTransport`). Nothing here was verified against a live chain or explorer.

## Defects fixed in place
1. **No address validation.** Receive address and token contract were never checked. Added `is_valid_tron_address` (34 chars, leading `T`, base58 alphabet, 25 bytes, version `0x41`, double-SHA256 checksum). `create()` now answers 503 `invalid_address` for a bad configured address/contract (not at boot, so the app still starts).
2. **Loose value parsing.** `Decimal(str(value))` accepted floats, `1e6`, fractions. Added `parse_micro` (integer string/int only, exact `Decimal`, no float).
3. **Loose matching.** A tx with no `token_info` was accepted; `to` and `block_timestamp` were not checked client-side (relied on the explorer's `min_timestamp`). Now: contract must match, `to` must match when present, `block_timestamp >= invoice.created`, non-empty `transaction_id`, and duplicates of the same amount resolve to the earliest mined block. Missing `block_number` (mempool) now means 0 confirmations (was 1) and never `paid`. `min_confirmations` floored at 1.
4. **Reorg left invoices stuck.** A `confirming` invoice whose tx vanished was never reverted (poll returned None and nothing handled it; confirming never expires). Sweep now moves it back to `awaiting_payment` (`status_reason=tx_disappeared`, tx_ref cleared; nothing is posted to the ledger before PAID) and extends `expires_at` to at least now+30 min (`REORG_GRACE`) so the re-mined transfer can still settle. Explorer outages (exceptions) are not treated as reorgs.
5. **One transfer could settle two invoices** (e.g. a reused suffix after expiry). `_apply_observation` now refuses a `tx_ref` already stored on another invoice of the same provider.

## Verified by tests (tests/test_usdt_tron_review.py)
Checksum/typo/EVM/length cases; 6-decimal exactness beyond float precision; confirmation boundary (19 vs 20, lagging node never negative); underpay/overpay/wrong token/other recipient/old tx/malformed entries never match; idempotent repeated sweeps (one ledger group, one outbox event); paid is final when the tx later vanishes; expiry vs late payment (sweep polls before expiring, so a transfer mined before TTL wins; a transfer for an already expired invoice does not settle and posts no ledger); ledger groups balance per currency, refund reverses to net zero, DB sums debit == credit (750.00); commission half-up cents + minimum fee.

## Known limitations / decisions (not defects of the skeleton, need an owner)
- **Under/overpaid and late transfers are not attributed**: they leave funds in the wallet with no invoice. Needs a manual reconciliation report (list inbound transfers not matched to any invoice). Not built; recommend an admin endpoint later.
- Partial payments are not summed. Overpay equal to another open invoice's `pay_amount` would be attributed to that invoice (inherent to the unique-amount scheme; keep suffix pool small per amount and open-invoice count low).
- A suffix freed by expiry can be reissued; the `block_timestamp >= created` check limits but cannot eliminate misattribution of a very late transfer to a newer invoice with the same amount.
- Lazy expiry on read can expire an invoice before the next sweep sees a transfer mined just before TTL. Run sweep frequently (< TTL margin) or add a grace window before launch.
- Paid is final: a deep reorg after 20 confirmations is treated as impossible (TRON finality ~19 SR confirmations); revisit if min confirmations is lowered.
- Ledger books the invoice amount (USD) at 1 USD = 1 USDT; the sub-cent suffix (<= 0.000999) and any depeg are not booked. Compliance/FX policy decision.
- Mock provider is deterministic and sets no `tx_ref` collisions across invoices when `tx_ref` is unique per call (default `mock_tx` is shared; use distinct values when confirming several invoices).

## Unverified wire assumptions (check against a live TronGrid before any launch)
- Path `GET /v1/accounts/{addr}/transactions/trc20` with `only_to`, `contract_address`, `min_timestamp`, `limit=200`; response `{"data":[...]}`.
- Fields: `transaction_id`, `value` (integer string, 6 decimals for USDT), `block_timestamp` (ms int), `to`, `token_info.address`. In real TronGrid, `block_number` may be absent from this endpoint (it is on `/v1/transactions/{id}` and event APIs); the code then reports 0 confirmations and the invoice would never reach `paid`. This likely needs a per-tx lookup or the events endpoint.
- `GET /v1/blocks/latest` is an assumption (TronGrid uses `POST /wallet/getnowblock` with `block_header.raw_data.number`).
- Pagination: `limit=200` with no `fingerprint` paging; a busy wallet can push a tx off page one, which looks like a vanished tx and reverts a confirming invoice until the next poll finds it again.
- Whether unconfirmed (mempool) transfers appear in the list, and `only_confirmed`/`only_unconfirmed` semantics.
- Rate limits and the `TRON-PRO-API-KEY` header name.

## Run results
- payments pytest: 106 passed. `ruff check services/payments`: clean (repo-wide ruff has 10 pre-existing errors in services/notifications tests).
- `scripts/contract_validate.py`: 0 mismatches.
- `scripts/e2e.py`: 33/35; the 2 failures (feed, freight) are `Connection refused` to those services, unrelated to payments (payments steps pass). `scripts/e2e_extended.py`: 15/19; failures in moderation, tracking relay, assistant quota, trust verification (404s / config), none in payments.
- No env vars need to be exported: the scripts set all `FF_*` values for the services they spawn.
