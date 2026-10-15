# Request: release a supplier's verification documents when a claim is revoked/released (trust)

From: gateway (implementing trust-claim-revocation-gateway.md). trust's contract (`contracts/openapi/trust.yaml`) has no endpoint to
purge or hide a supplier's verification documents, so the gateway cannot do it. Gateway now: revoke/reject/self-release clear
`supplier_id` and write an append-only `claim_decisions` row (user, supplier, action, reviewer, reason).

Needed from trust (additive): an admin endpoint, e.g. `POST /v1/admin/trust/verification/suppliers/{supplier_id}/release`, that makes the
supplier's documents unreadable to a later claimant (soft-delete or reset to `released`, keep rows for audit). Once it exists, the gateway will
call it from revoke/self-release and add it to the admin allow-list. Until then admins must check the document list before approving a re-claim.
