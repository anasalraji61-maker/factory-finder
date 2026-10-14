# Request: gateway routing for trust verification documents

From: trust. Contract: `contracts/openapi/trust.yaml`. No gateway code was changed.

1. Supplier endpoints, **authenticated users with a verified supplier claim only**:
   `POST|GET /v1/trust/verification/documents`, `DELETE /v1/trust/verification/documents/{id}` -> trust, same paths.
   Forward `X-Supplier-Id` from the DB (as for `/v1/my/*`; extend the upstream list in `proxy.py` that attaches it with `trust`) and
   `X-Internal-Token`. Reject (403) when the user has no verified claim. Treat non-GET as a sensitive write (email-verified).
   Body limit: JSON metadata only (files are uploaded to media first).
2. Public: `GET /v1/trust/suppliers/{id}/verification` and the existing `GET /v1/trust/suppliers/{id}` (now has `verification_level`) stay public.
3. `/v1/admin/trust/verification/*` -> trust, same path, **admin users only** (403 otherwise). The gateway adds `X-Admin-Token`
   (gateway setting = `FF_TRUST_ADMIN_TOKEN`, never from the client) and optionally `X-Reviewer: <admin user id>` so the audit log names the reviewer.
   Put the prefix before the gateway's own `/v1/admin` handling.
4. Mobile: show the badge (`verification_level`, labels from `/verification`), and the owner list with status, reason and `number_masked`.
