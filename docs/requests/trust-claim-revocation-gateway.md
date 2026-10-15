# Request: supplier-claim revocation and reviewer identity (gateway)

From: trust (review of the claim -> verification flow). No gateway code was changed.

1. `/v1/admin/supplier-claims/{user_id}/approve|reject` only act on `pending`; there is no way to revoke a `verified` claim. Add `.../revoke`
   (verified -> none, supplier_id released). The proxy already reads the claim from the DB per request (5 s cache), so X-Supplier-Id stops at once.
2. Claim decisions have no reviewer identity or audit trail. Record admin user id, action, reason and time append-only (same pattern as trust's audit).
3. Always send `X-Reviewer: <admin user id>` on `/v1/admin/trust/verification/*`; without it trust records the actor as plain `admin`.
4. Releasing/revoking a claim leaves the supplier's verification documents (masked numbers, file refs) readable by the next claimant of that supplier_id.
   Re-claims should require fresh admin approval (already true) and admins should check the document list before approving.
