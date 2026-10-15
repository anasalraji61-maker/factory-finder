# Security review 2026-10-g (rfq, tracking, geo)

Scope: deal/offer/request lifecycle, ownership, bounds, tracking relay and provider skeletons. Rounds a..f not repeated.

## Fixed in place (with tests)

rfq
- `accept_offer` raised `decimal.InvalidOperation` (HTTP 500) / lost precision for large qty x price (28-digit default context); the supplier-net subtraction in `deal_dict` had the same precision loss. Both now run at 80-digit precision.
- Offer expiry / request deadline were only enforced through the throttled sweep (up to 30 s stale for rows written by another process). `accept_offer` now checks `valid_until` and `deadline` itself.
- Concurrent accept/withdraw/close/offer on one request: request row is now locked (`FOR UPDATE`, no-op on SQLite) and the offer is re-read after the lock; a unique-constraint race on `deals.request_id/offer_id` returns 409 `already_awarded` instead of 500.
- Unbounded offers: max 5 active offers per supplier per request and 500 per request (409 `offer_limit_reached`).

tracking
- Per-user shipment cap (`FF_TRACKING_MAX_SHIPMENTS_PER_USER`, default 200; 409 `shipment_limit_reached`): each create hits the provider.
- Concurrent create of the same reference -> 409 `duplicate_shipment` instead of 500.
- Provider skeletons re-validate container / B/L / AWB / IMO format before building URLs (defence in depth); no network call on malformed input.
- Provider response bounds: events capped at 300 per snapshot, descriptions at 300 chars, response cache capped at 1000 entries.
- A stale/partial provider snapshot can no longer reopen a `delivered` shipment.
- Outbox retention: relay purges delivered/dead rows older than `FF_TRACKING_OUTBOX_RETENTION_DAYS` (30), hourly; pending rows never purged.
- `/v1/validate/{type}/{reference}` reference capped at 64 chars.

geo
- `q` (100) and `country` (8) query params length-capped (country code is echoed in the 404 message).

## Open (not safe to change inside this lane or needs a product decision)

1. rfq `create_offer` does not check request visibility: any authenticated user who knows a private request id can offer on it. Ids are 128-bit random so exploitation needs a leaked id; decide whether private requests need an invite list (new field, additive).
2. rfq has no price/currency amendment endpoint after acceptance (good); the deal copies price at accept time. Payments verifies amounts via `amount_mismatch`. No change needed, noted as an invariant to keep.
3. rfq `confirm_receipt` lets the buyer complete without supplier `delivered` (by design, event data records `supplier_marked_delivered`). Reviews are allowed from `paid`; a later refund leaves the review published. Consider hiding reviews of refunded/disputed deals.
4. rfq deal event `seq` is `count()+1` under a row lock; fine on PostgreSQL, relies on `with_for_update` (unique `(deal_id, seq)` is the backstop).
5. tracking: deleting a shipment leaves its pending outbox rows, so a deleted shipment can still notify until retention/dead. Needs notifications-side owner check or an outbox delete (tracking lane, low risk; not done to keep outbox history).
6. tracking relay is single-consumer by assumption; two relay instances may send the same row twice (harmless: notifications dedupes on `dedupe_key`).
7. tracking `label`/`carrier` are free text (max 120/80) forwarded to notifications; control characters not stripped.
8. Real-provider wire shapes remain UNVERIFIED (unchanged); response body size is not capped before `r.json()` (needs httpx streaming).
