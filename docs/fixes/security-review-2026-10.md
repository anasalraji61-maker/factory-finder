# Security review (QA) - deferred items

1. HIGH - Supplier identity is self-claimed. `PATCH /v1/me {supplier_id}` lets any user claim any unclaimed `sup_*` id
   (first come). The gateway then forwards it as the verified `X-Supplier-Id` to messaging, so the claimer reads and
   answers that supplier's conversations. Needs a verification flow (admin approval / proof of ownership) before
   launch; until then treat supplier ids as unverified. Owner: gateway.
2. DONE (2026-10) MEDIUM - Refresh tokens are stateless JWTs (30 days): no rotation, no reuse detection, no revocation, and
   logout/password-change cannot invalidate them. Needs a `refresh_tokens` table (jti, family, used_at). Owner: gateway.
3. MEDIUM - Rate limiting is per client IP, in memory, per process. Behind a proxy/LB every client shares one IP
   (set `--proxy-headers` + trusted forwarded IPs) and multiple replicas multiply the limit; use Redis. No per-account
   login lockout. Owner: gateway.
4. MEDIUM - Direct service ports trust `X-User-Id` when `FF_INTERNAL_TOKEN` is unset. sourcing/geo never check the
   token, and sourcing->trust / notifications->sourcing / rfq->sourcing clients do not send it, so the token cannot
   be turned on for trust/logistics yet. Compose now publishes only the gateway; keep backends on a private network.
5. DONE (2026-10) LOW - rfq `supplier_ref` / `supplier_name` on offers are client-supplied and not tied to the caller's verified
   supplier id (impersonation of a listed supplier's name). Fix together with item 1 via a request in
   docs/requests/rfq-supplier-identity.md.
6. DONE (2026-10) LOW - CORS defaults to `*` (no credentials; bearer auth). Set `FF_GATEWAY_CORS_ORIGINS` in production.
7. ACCEPTED/DOCUMENTED LOW - WebSocket auth via `?token=` query is supported; the gateway now redacts it in uvicorn access logs, but
   any other proxy in front must also scrub it. Prefer the Authorization header where the client allows.

## Resolution notes (2026-10)
- Item 2: `refresh_tokens` table (sha256 of jti, family, used_at, revoked_at). `/v1/auth/refresh` rotates (single-use); replaying a used
  token revokes its whole family; `POST /v1/auth/logout {refresh_token}` revokes the family (always 204). Response shape unchanged.
  Refresh tokens issued before this change (no jti) are rejected once: clients re-login. Password change does not exist yet; when added it must revoke all families.
- Item 5: rfq ignores body `supplier_ref`; `supplier_ref` = gateway-verified `X-Supplier-Id` (forwarded to rfq only for admin-verified claims) else null;
  responses gain additive `supplier_verified`. `supplier_name` stays a free display label (not identity).
- Item 6: CORS default is now no origins; set `FF_GATEWAY_CORS_ORIGINS='["http://localhost:3000"]'` for web dev. Compose/.env.example default `[]`.
- Item 7: unchanged by decision; `?token=` stays (log-redacted); any extra proxy must scrub it. Documented in gateway README.
- Still open: items 1 (supplier verification is admin flow only), 3 (rate limit behind proxy), 4.
