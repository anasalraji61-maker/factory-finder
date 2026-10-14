# Request: gateway routing for sourcing moderation

From: sourcing. Contract: `contracts/openapi/sourcing.yaml`.

1. `POST /v1/listings/{id}/report` -> sourcing, **authenticated users only** (not public; GET `/v1/listings/*` stays public).
   Forward `X-User-Id` (verified) and `X-Internal-Token`. Optionally also forward `X-Supplier-Id` for verified suppliers
   (as for `/v1/my/*`) so reporting your own listing is rejected (409). Counts as non-sensitive write; email-verified requirement optional.
2. `/v1/admin/moderation/*` -> sourcing `/v1/admin/moderation/*` for **admin users only** (403 otherwise). The gateway must
   add `X-Admin-Token` itself (value = `FF_SOURCING_ADMIN_TOKEN`, a gateway-side setting; never from the client) plus
   `X-Internal-Token`. Add `/v1/admin/moderation` to the route table before the gateway's own `/v1/admin` handling.
3. Owner statuses `pending_review`/`hidden` and `moderation_*` fields already flow through `/v1/my/listings*`; the mobile app should show them.
