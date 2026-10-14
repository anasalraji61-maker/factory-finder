# deal-reviews decisions

- 2026-10-14 Reviews live in rfq (it owns deals); reads are exposed at `/v1/suppliers/{ref}/reviews|review-summary`, so the gateway routes exactly those two paths to rfq before the sourcing `/v1/suppliers` prefix (public GET already covered by that prefix; writes stay authenticated).
- 2026-10-14 Eligible deal statuses: paid, in_fulfilment, completed (`pending_payment`, `disputed`, `cancelled` -> 409 `deal_not_reviewable`). rfq has no endpoint moving a deal past pending_payment yet (payments does not call back); reviews become usable once that transition exists.
- 2026-10-14 Reviews are keyed by the offer's gateway-verified `supplier_ref`; a deal whose offer had no verified supplier cannot be reviewed (409 `supplier_unverified`) - there is no public supplier identity to attach it to.
- 2026-10-14 One review per deal forever (unique deal_id): deleting does not free the slot, which blocks delete-and-repost churn.
- 2026-10-14 Edit/delete window is 24h from creation (not from last edit); delete is a soft delete, `review_events` keeps created/edited/deleted/replied/reported with the previous values.
- 2026-10-14 Non-party on POST deal review -> 404 (no existence leak); the deal's supplier -> 403; non-author on PUT/DELETE -> 403 (review ids are public anyway).
- 2026-10-14 Reviewer label "First L." is computed once at creation from the gateway-set `X-User-Name` (percent-encoded; the gateway whitelists client headers so it cannot be spoofed); missing/email-like names -> "Verified buyer". Email is never stored.
- 2026-10-14 Spam filter: strip control/format (bidi, zero-width) chars, NFKC + Unicode-digit normalisation before detecting URLs (scheme, www, common TLDs, t.me/wa.me), emails, and 9+ digit runs; hits -> 422 `prohibited_content`. Deliberately conservative; 9 digits so ISO dates do not trip it.
- 2026-10-14 Reports: idempotent per (review, user), 10/hour/user (DB-counted, so it survives restarts and works with the fake clock) -> 429; only sets `flagged_for_review`, never hides. No moderation endpoint yet.
- 2026-10-14 Average is Decimal half-up to 2 places, returned as a string; histogram keys "1".."5".
- 2026-10-14 Trust not edited: see docs/requests/trust-reviews.md.
