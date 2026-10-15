# Security review 2026-10-j (rfq, messaging, payments)

Scope: authz/IDOR, races (double accept/pay/refund), unbounded input, PII in logs, idempotency, money rounding, webhook replay/timing.
Result: 3 real defects fixed (tests first), no authz/IDOR hole, no race hole found. Suites green, ruff clean.

## Fixed
1. **payments: invoices could be created for a refunded/disputed deal** (`service._resolve`). The rfq deal status was ignored, so after a refund the buyer could create and pay a fresh invoice that rfq can never settle (money taken for a dead deal). Now 409 `deal_not_payable` for `refunded`/`disputed` (a deal without `status`, e.g. old mocks, is unaffected).
2. **payments: zero-decimal currencies (IQD/JPY) in `compute_commission`** used cents while rfq uses whole units, so an admin `commission_basis` invoice differed from the deal commission (e.g. 32894.74 vs 32895) and rfq would dead-letter the paid callback as `amount_mismatch`. Now whole units, identical to rfq.
3. **messaging: unbounded block list + check-then-insert race**. `PUT /blocks/{id}` had no cap (row growth per user) and a concurrent duplicate PUT could hit the PK and return 500. Added `FF_MAX_BLOCKS_PER_USER` (default 1000 = what `list_blocks` returns; 0 = unlimited; 409-class `block_limit_reached`, re-blocking never counts) and a savepoint around the insert.
Tests: `services/payments/tests/test_security_review_j.py`, `services/messaging/tests/test_security_review_j.py`.

## Reviewed, no defect
- payments webhook: HMAC over `t.body`, all candidates compared constant-time, timestamp window checked, body capped before HMAC (64 KB), `(provider,event_id)` replay row + unique index, stale events never reach dedupe pruning (retention 180 d >> 300 s window); on-chain providers ignore callbacks (explorer poll only); amount mismatch -> review, never settles.
- payments settle/refund/cancel/expire: compare-and-set on status, one ledger post per transition, tx_ref unique across invoices, outbox lease + per-deal ordering; refund is admin-only and ledger-reversing.
- payments authz: non-owners get 404 on get/cancel; payee never sees the payer memo; non-admins cannot choose payer/payee/amount.
- rfq: every deal/review/offer mutation checks party or ownership under `FOR UPDATE`; accept/award is serialised by the request row lock plus unique `deals.request_id/offer_id`; payment callback is idempotent by `event_id`, amount-checked, refunded-is-terminal.
- rfq money: subtotal half-up to the currency minor unit with prec 80, zero subtotal rejected, 32-char overflow guard.
- messaging: access via participant check on every route and WS, neutral 404 for blocks, per-sender idempotency key, `mark_read` scoped to the conversation, cursor strictly validated, logs carry ids only (no bodies/headers/query).

## Not fixed (needs an owner decision)
- **rfq `require_both_invoices` defaults to false**: with only one invoice known, that one settles the deal. A buyer who pays just the commission invoice (never creating `deal_payment`) moves the deal to `paid` and the supplier may start fulfilment unpaid; paying only `deal_payment` skips the commission. Flipping the default (or forcing it under `FF_ENV=production`) is a product/architect decision because payments' clients may create a single invoice. Recommended: set `FF_RFQ_REQUIRE_BOTH_INVOICES=true` in production, or have payments create both invoices when the deal is awarded.
- **payments webhook `payment.confirmed` without `amount`** (contract: optional) skips the amount check for non-on-chain providers (mock). Signed by the provider, so low risk; a real fiat provider adapter should make `amount` mandatory before enabling it.
- **payments/rfq treat `platform` / `system:payments` as plain strings**: an `X-User-Id: platform` would see commission invoices (payee `platform`). Only reachable if the gateway ever forwards an attacker-chosen id; gateway ids are server-generated. Fix would change an existing test (`test_payee_never_sees_payers_memo_via_api` uses `platform` as a user).
- **rfq 403 vs 404 on offer actions** (withdraw/reject/accept of a foreign offer id answers 403, not 404) is asserted by existing tests/contract; offer ids are 128-bit random so this is not an enumeration risk.
- Request-body size for rfq and payments (non-webhook) relies on the gateway/ingress cap; messaging enforces its own `max_body_bytes`.
