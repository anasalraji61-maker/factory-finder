# Request: notifications <- tracking outbox

From: tracking. To: notifications (and gateway if exposed). Status: open (tracking side done).

tracking writes one row per shipment change into table `tracking_outbox` (migration 0002): `id`, `dedupe_key` (unique),
`shipment_id`, `owner_id`, `kind` (`status_changed` | `shipment_delayed`), `payload` (JSON), `created_at`, `delivered_at`.
Payload keys: shipment_id, owner_id, reference, reference_type, label, kind, status, previous_status, eta, delayed,
delay_hours, event_id, occurred_at.

Proposed integration (notifications owner decides): tracking adds `GET /v1/internal/outbox?after_id=&limit=` and
`POST /v1/internal/outbox/{id}/ack` (internal token), additive in `contracts/openapi/tracking.yaml`; notifications polls
it, maps `kind` to a push/digest entry for `owner_id` (ar/en text from `status`), and acks. Alternative: notifications
exposes an ingest endpoint and tracking pushes. Until then rows accumulate harmlessly (`delivered_at` stays null).
