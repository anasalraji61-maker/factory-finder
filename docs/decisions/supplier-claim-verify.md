2026-10-13 | `PATCH /v1/me {supplier_id}` now records a pending claim; gateway forwards X-Supplier-Id (HTTP+WS) only when `supplier_claim_status == verified` | fixes HIGH finding (self-claimed supplier identity) in docs/fixes/security-review-2026-10.md
2026-10-13 | Admin approval via `FF_GATEWAY_ADMIN_TOKEN` + `X-Admin-Token` (constant-time; 404 when unset, 401 when wrong); reject/release clears supplier_id | simplest verification without a new admin UI/role system
2026-10-13 | sqlite add-column-if-missing at startup; pre-existing claims migrate to `pending` | old unverified claims must not stay trusted
2026-10-13 | Mobile Me: missing `supplier_claim_status` => none (no id) or verified (id present, older server); mock claim => pending | tolerant parsing
