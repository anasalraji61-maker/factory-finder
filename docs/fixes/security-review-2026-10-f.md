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

## Open (design / product decision)
- **demand**: `signals`/`drafts` tables have no retention (admin-only writes, so low risk); needs a policy (e.g. purge ignored/no_match signals > 90 days).
- **payments**: `webhook_events`, `outbox_events` (delivered), `payment_attempts` grow forever (financial records; archive policy needed). A payer can
  cancel and re-create invoices without a per-user cap (each creates a provider charge); consider a per-deal/per-user creation limit.
- **messaging**: no per-user cap on number of conversations or messages per conversation; rate limiters are in-process (not shared across replicas).
  Erasure keeps message text of the erased user (documented decision) - free text may still contain PII.
- **assistant**: anonymous quota is keyed by the peer address, which behind the gateway is the gateway's address (one shared bucket); gateway should forward a client key.
- **notifications**: `register_device` re-assigns an existing push token to the caller (device moves accounts); safe only because tokens are secret per device.

## Env vars for scripts/e2e.py
None required (all new settings have defaults).
