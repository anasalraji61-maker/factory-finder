# DONE (trust) - Request: release a supplier's verification documents when a claim is revoked/released (trust)

From: gateway (implementing trust-claim-revocation-gateway.md). trust's contract (`contracts/openapi/trust.yaml`) has no endpoint to
purge or hide a supplier's verification documents, so the gateway cannot do it. Gateway now: revoke/reject/self-release clear
`supplier_id` and write an append-only `claim_decisions` row (user, supplier, action, reviewer, reason).

Needed from trust (additive): an admin endpoint, e.g. `POST /v1/admin/trust/verification/suppliers/{supplier_id}/release`, that makes the
supplier's documents unreadable to a later claimant (soft-delete or reset to `released`, keep rows for audit). Once it exists, the gateway will
call it from revoke/self-release and add it to the admin allow-list. Until then admins must check the document list before approving a re-claim.

## Status: DONE (trust)

Implemented: `POST /v1/admin/trust/verification/suppliers/{supplier_id}/release` (contract `contracts/openapi/trust.yaml`).
Gateway owner: call it from revoke / reject / self-release (service-to-service) with header `X-Admin-Token: <FF_TRUST_ADMIN_TOKEN>`
(plus `X-Internal-Token` when `FF_INTERNAL_TOKEN` is set), optional `X-Reviewer`, optional body `{"reason": "..."}`, using the supplier id
that was just released (before or right after clearing `supplier_id`). Add the path to the admin allow-list. Response 200
`{supplier_id, released_documents, withdrawn_documents, verification_level}`; idempotent (repeat call returns 0/0); 404 when the admin
token is not configured, 401 on a wrong token. Effect: live documents are withdrawn (audited as `withdraw` by `admin`), all rows are kept
but hidden from owner reads (`released_at`, migration 0003), the cached score/badge is invalidated, so the next claimant sees no documents
and starts unverified. Files stay bound to the old rows (a re-upload of the same media file by another supplier is still refused).
