# Deal payment hook (payments -> rfq) and deal lifecycle

2026-10-14 decisions (rfq + payments; gateway unchanged).

- **Hook**: payments writes an `outbox_events` row in the SAME transaction as every invoice `-> paid` / `-> refunded` move, then
  delivers it to `POST /v1/internal/deals/{id}/payment-status` (rfq). Settlement never waits on rfq: an inline best-effort
  attempt (<= 3 s) follows webhook/refund commits, and `POST /v1/payments/sweep` drains the rest.
- **Delivery**: idempotent by `event_id` (`<invoice_id>:<paid|refunded>`), per-deal order kept (a waiting/dead event blocks later
  ones of that deal), backoff 30 s doubling (cap 1 h), `dead` after 8 attempts or a permanent 4xx from rfq (e.g. `amount_mismatch`).
  Admin: `GET /v1/payments/outbox?status=dead`, `POST /v1/payments/outbox/{id}/requeue`.
- **Auth**: internal token only (`X-Internal-Token`, enforced by the rfq middleware and again on the route). The gateway has no
  route for `/v1/internal/*` (404; test in gateway `test_proxy.py`).
- **Paid rule**: deal -> `paid` when every invoice kind payments has reported is paid. A kind becomes known when it is settled or listed
  in `other_open_kinds` of another event (payments computes it from the deal's other live invoices). Both invoices existing => both must
  be paid; only one existing => that one suffices. Gap: a buyer who pays the supplier before a commission invoice exists makes the deal
  `paid` without commission; set `FF_RFQ_REQUIRE_BOTH_INVOICES=true` to always require both.
- **Refund**: deal_payment refunded in `pending_payment|paid` -> `refunded` (terminal; a late `paid` event never revives it); in
  `in_fulfilment` -> `disputed` (human decides); after `completed` only logged. Commission refunded while `paid` -> back to
  `pending_payment` (buyer pays a new commission invoice).
- **User transitions**: supplier `fulfilment/start` (paid -> in_fulfilment), supplier `delivered` (stamps `delivered_at`, status stays),
  buyer `confirm-receipt` (in_fulfilment -> completed; does not require `delivered`). All idempotent when already done, 404 for non-parties,
  403 for the wrong side. Supplier side also needs the verified `X-Supplier-Id` when the offer carried a supplier ref (unverified
  offers have no ref, so the supplier user id alone is enough).
- **Event log**: `deal_events` (append-only, ORM refuses update/delete, `(deal_id, seq)` unique, `event_id` unique). Exposed to
  parties as `GET /v1/deals/{id}/events` with roles (buyer/supplier/system), never user ids.
- Reviews use the existing `paid | in_fulfilment | completed` gate; `refunded` deals are not reviewable.
