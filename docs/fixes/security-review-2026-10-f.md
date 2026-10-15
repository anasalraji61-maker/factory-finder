# Security review 2026-10-f (assistant, notifications, demand, payments, messaging)

## Fixed in place (tests in each service's `tests/test_security_review.py`)
- **notifications**: unbounded alert inbox / delivery log. Per-owner cap (`FF_NOTIFICATIONS_MAX_ALERTS_PER_USER`, default 1000, newest kept,
  enforced in the same txn as insert) plus age retention in the scheduler (`..._ALERT_RETENTION_DAYS` 180, `..._DELIVERY_RETENTION_DAYS` 30;
  only non-pending deliveries are pruned). Request bodies: saved-search fields, money strings, `channels` map/list, evaluate ids now length-capped.
- **demand**: per-draft `audit` JSON grew on every repeatable call (`outcome`); capped at 50 entries (first entry kept).
- **payments**: unauthenticated webhook route buffered the whole body before the HMAC check; now streamed with a 64 KiB cap (422 `payload_too_large`).
  The payer's free-text `user_memo` was returned to the payee through `GET /invoices[/{id}]`; now only payer/admin see it.
  `X-User-Id` longer than 64 chars is refused.
- **messaging**: creating conversations was unlimited (inbox spam to arbitrary user ids); new conversations are rate limited per user
  (`FF_MESSAGING_CONVERSATION_CREATE_LIMIT` 10 / `..._WINDOW_SECONDS` 60; dedupe hits are free). WS `read` frame with a non-string `message_id` could raise an
  unhandled error and drop the socket; now ignored/coerced.
- **assistant**: tracking-validator `reason` (downstream text) went into the answer and the LLM rewrite unsanitised; now passes through the injection guard.
  Daily quota counter map is capped (200k keys, fail closed for new keys) so spoofed ids/addresses cannot grow memory. `destination.city` capped at 80 chars.

## Fixed (follow-up, 2026-10-15)
- **demand** (FIXED): retention in `DemandService.prune()` (runs at the end of `POST /v1/signals/poll`): ignored/no_match signals older than
  `FF_DEMAND_SIGNAL_RETENTION_DAYS` (90) and rejected drafts + their signal older than `FF_DEMAND_REJECTED_DRAFT_RETENTION_DAYS` (90); 0 = keep.
  draft/approved/published drafts (audit) and their signals are never purged.
- **payments** (FIXED): per-payer caps for non-admin creation: `FF_PAYMENTS_MAX_OPEN_INVOICES_PER_USER` (20, pending/awaiting/confirming) and
  `..._MAX_INVOICES_PER_USER_PER_DAY` (50, any status, rolling 24 h) -> 429 `too_many_open_invoices` / `daily_invoice_limit`; idempotent hits are free.
  Retention in `prune()` (end of `POST /v1/payments/sweep`): `webhook_events` > `..._WEBHOOK_EVENT_RETENTION_DAYS` (180, never those of paid/refunded invoices;
  signature tolerance is 5 min so replay is still blocked), delivered `outbox_events` > `..._OUTBOX_DELIVERED_RETENTION_DAYS` (180),
  `payment_attempts` > `..._ATTEMPT_RETENTION_DAYS` (365, only of expired/failed invoices). Invoices, ledger, paid/refunded history, pending/dead outbox are never pruned.
- **messaging** (FIXED): `FF_MESSAGING_MAX_CONVERSATIONS_PER_USER` (1000, creator only; dedupe hits and platform accounts exempt) -> 409 `conversation_limit_reached`;
  `FF_MESSAGING_MAX_MESSAGES_PER_CONVERSATION` (10000) -> 409 `conversation_full` (idempotent retries still answered). 0 = unlimited.
  Erasure now blanks the user's message `text`, `client_message_id`/`dedupe_key`, the inbox preview of their last message and titles of threads they created
  (export returns the text before erasure; sender ids/attachments were already tombstoned). Counterparty messages are untouched.

## Open (design / product decision)
- **messaging**: rate limiters are in-process (not shared across replicas).
- **assistant**: anonymous quota is keyed by the peer address, which behind the gateway is the gateway's address (one shared bucket); gateway should forward a client key.
- **notifications**: `register_device` re-assigns an existing push token to the caller (device moves accounts); safe only because tokens are secret per device.

## Env vars for scripts/e2e.py
None required (all new settings have defaults; e2e invoice/conversation volumes are far below the caps).

## Update: assistant anonymous quota key
Gateway now sends `X-Client-Ip` (same `client_ip()` derivation as its rate limiter; client-supplied copies stripped) on every `/v1/assistant` call. The assistant uses it
for the anonymous bucket only if the request carries the valid `FF_INTERNAL_TOKEN` or `FF_ASSISTANT_TRUST_CLIENT_IP_HEADER=true`; value must parse as a single IP, else peer address.
Note: gateway currently requires auth for `/v1/assistant`, so anonymous traffic only appears if that route is made public.
