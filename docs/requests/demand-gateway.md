# Request: gateway route for demand (admin-only)

From: demand. Not required yet; the service is internal (port 8110, not published in docker-compose).

When ready, the gateway should proxy `/v1/admin/demand/*` -> `http://demand:8110/v1/*` for **admin users only** (403 otherwise), forwarding `X-User-Id` (the admin's id, used for the audit log) and `X-Internal-Token`. Add `"demand": "http://demand:8110"` to the gateway upstream map. Contract: `contracts/openapi/demand.yaml`. Never expose these routes to normal users.
