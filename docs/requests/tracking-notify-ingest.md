# Request: tracking -> notifications ingest (reply to tracking-notify.md)

From: notifications. To: tracking (or the orchestrator). Status: notifications side done.

notifications chose the push model. `POST /v1/internal/tracking-events` (`contracts/openapi/notifications.yaml`, header `X-Internal-Token`)
takes `{"events": [<outbox row>, ...]}` (<= 100) where a row is `{id, dedupe_key, shipment_id, owner_id, kind, payload}` exactly as in `tracking_outbox`.
Response lists per-event `created | duplicate | invalid`; `created` and `duplicate` are both safe to treat as delivered.

Needed on the tracking side (not done by notifications): a relay that selects rows with `delivered_at IS NULL` in id order, POSTs them in batches,
and sets `delivered_at` for every row whose result is `created` or `duplicate` (leave `invalid` ones for inspection). Replays are harmless (idempotent by `dedupe_key`).
Gateway exposure is not needed: this route is internal only.
