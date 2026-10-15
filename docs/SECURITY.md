# Security model — Factory Finder

_Written 2026-10-15 from the code (`services/*/src`) and the review logs in `docs/fixes/`. This is a summary with pointers; the code and tests are the source of truth. Open findings are listed in `docs/fixes/INDEX.md`. Operations (rotation, incidents) are in `docs/RUNBOOK.md`; deployment in `docs/DEPLOY.md`; the short architecture view is `docs/ARCHITECTURE.md` section 7._

## 1. Trust boundaries

- Only the gateway (`:8000`) is published. Clients (Flutter app, admin console) speak `/v1/*` with a bearer JWT. Backends (`:8101-8114`) sit on the `internal` network.
- The gateway authenticates, then forwards identity to services as `X-User-Id`, `X-Internal-Token`, `X-Request-Id`, and `X-Supplier-Id` (only for an admin-verified supplier claim, read from the gateway DB). Client copies of `X-User-Id`, `X-Internal-Token`, `X-Admin-Token`, `X-Supplier-Id`, `X-Client-Ip` are never forwarded; response headers pass an allow-list (no `Set-Cookie`).
- Services accept `X-User-Id` only with a matching `FF_INTERNAL_TOKEN`. When that token is unset and `FF_ENV` is not `production`, the check fails open (dev only, known item in `docs/fixes/security-review-2026-10-e.md`).
- Path policy runs on the decoded path: `.`, `..`, empty segments, backslashes and still-encoded `%2e`/`%2f`/`%5c` are refused with 400; internal-only paths (`/v1/internal/*`, `/v1/alerts/evaluate`, `/v1/alerts/digest`, `/v1/media/admin`) have no external route.

## 2. Authentication and sessions (gateway)

- Access token: HS256 (`jwt_algorithm` restricted to HS256/384/512, never `none`), 15 min, carries `iss`/`aud` and a token version claim `tv`. Key rotation through the previous-secret setting (`docs/RUNBOOK.md` section 4).
- Refresh token: 30 days, server-tracked (hashed jti + family), single use. Replaying a used token revokes the whole family. `POST /v1/auth/logout` revokes one family; `POST /v1/auth/logout-all` revokes every family and bumps the user's `token_version`.
- Token versions: every access token must match the user's current `token_version` (`domain/security.py: token_version_ok`). Password reset, password change, `logout-all` and deactivation bump it, so previously issued access tokens stop working immediately (a token without `tv` is accepted only while the user's version is still 0). Password change, password reset and email change require `current_password` or a reset token.
- Disabled users: `is_active` is re-checked on every proxied request (5 s cache), so a block takes effect within about 5 s.
- Login abuse: bcrypt check always runs (no timing oracle for unknown accounts); per-IP limits plus a per-account failed-login soft block (hashed identifier, `FF_GATEWAY_LOGIN_FAIL_LIMIT_PER_MINUTE`). Per-IP and per-user write limits, body-size caps with a slow-upload timeout (`HttpGuardMiddleware`, all HTTP methods), per-upstream circuit breaker, trusted-proxy-aware client IP (memory or Redis counters).
- Email verification (optional enforcement `FF_GATEWAY_REQUIRE_EMAIL_VERIFIED`) gates payments writes, claims and listings; verification and reset tokens are hashed and single use.
- Admin: `X-Admin-Token` equals `FF_GATEWAY_ADMIN_TOKEN` (constant-time compare; failed attempts throttled per IP; the routes answer 404 when the token is unset). Allow-listed passthroughs to service admin routes; the gateway injects each service's admin token and a fixed `admin` actor. There is a single shared admin token with no per-admin identity (open, `docs/fixes/security-review-2026-10-h.md` item 7).
- Supplier identity: `PATCH /v1/me {supplier_id}` creates a pending claim (first claimer wins); only an admin-approved claim yields `X-Supplier-Id` and unlocks `/v1/my/*` and trust verification writes. Approve, reject and revoke are audited (`claim_decisions`), and revoking a claim releases the supplier's verification documents in trust.

## 3. WebSocket tickets

Chat runs over `WS /v1/ws/conversations/{id}` proxied by the gateway to messaging.
- `POST /v1/ws-ticket` (authenticated, version-checked) mints a ticket valid `FF_GATEWAY_WS_TICKET_TTL_SECONDS` (30 s), single use (consumed atomically; Redis `GETDEL` when Redis is configured), capped in number and rate limited per user.
- The legacy `?token=` query parameter is off by default (`FF_GATEWAY_WS_ALLOW_TOKEN_PARAM=false`) because tokens in URLs leak into proxy logs.
- Handshakes share the per-IP bucket (close code 4429 when throttled), at most `FF_GATEWAY_WS_MAX_CONNECTIONS_PER_USER` (5) concurrent sockets per user, a maximum session length, and a client frame size cap. Messaging re-checks access (including blocks) before each broadcast.
- Tests: `services/gateway/tests/test_ws.py` (ticket single-use, expiry, store cap, token param off by default, per-user cap, rate limits, session lifetime), `test_token_version.py::test_ws_ticket_and_token_handshake_respect_version`, `test_ws_redis.py`; messaging `tests/test_concurrency_qa2.py`.

## 4. Production fail-closed guards

With `FF_ENV=production` a service refuses to start (`RuntimeError: FF_ENV=production requires ...`) instead of running unsafely, and OpenAPI/Swagger (`/docs`, `/redoc`, `/openapi.json`) are disabled. Full table and recovery steps: `docs/RUNBOOK.md` section 4.

| Service | Required |
|---|---|
| All except geo | `FF_INTERNAL_TOKEN` |
| gateway | `FF_GATEWAY_JWT_SECRET` (>= 32 chars), `FF_GATEWAY_ADMIN_TOKEN`, `FF_GATEWAY_CORS_ORIGINS` without `*` |
| sourcing | `FF_SOURCING_REPORTER_HASH_KEY` (not the public default), `FF_SOURCING_ANALYTICS_HASH_KEY` |
| payments | provider not `mock`, its `FF_PAYMENTS_WEBHOOK_SECRET_<PROVIDER>` (unless `off`), `FF_PAYMENTS_ADMIN_TOKEN` |
| media | `FF_MEDIA_SIGNING_KEY` |
| trust | `FF_TRUST_VERIFICATION_HASH_KEY` (also refused at startup if it differs from the key behind stored fingerprints) |

Compose defaults every secret to empty, which disables admin routes (404) and never ships a default token; set `FF_ENV=production` in any real deployment (`docker-compose.prod.yml` enforces it). Containers drop all capabilities, run non-root, and only the gateway publishes a port.
Tests: `test_production_guard.py` in assistant, demand, logistics, media, messaging, notifications, payments, rfq, sourcing, tracking; `feed/tests/test_security.py` and `freight/tests/test_security.py` (`test_production_requires_internal_token`); `gateway/tests/test_moderation_routing.py::test_production_guard`; `trust/tests/test_persistence.py::test_production_requires_hash_key`; `geo/tests/test_production_docs.py`.

## 5. Service-to-service and admin tokens

- `FF_INTERNAL_TOKEN` is identical on the gateway and all services; a mismatch answers 401 `invalid_internal_token`.
- Per-service admin tokens (`FF_PAYMENTS_ADMIN_TOKEN`, `FF_SOURCING_ADMIN_TOKEN`, `FF_TRUST_ADMIN_TOKEN`, `FF_MEDIA_ADMIN_TOKEN`, `FF_FEED_ADMIN_TOKEN`, `FF_FREIGHT_ADMIN_TOKEN`) are held by the owning service and the gateway only; unset on either side means 404.
- Payments webhooks are the one public service route (dedicated ingress, `docs/DEPLOY.md`): HMAC-SHA256 `X-FF-Signature`, 300 s tolerance, event-id replay protection, 64 KiB body cap streamed before verification. Private media URLs are HMAC-signed and valid for 5 minutes (bearer links by design).

## 6. Lawful sourcing and demand matching

- Every external source is an adapter behind an interface, with a deterministic mock; tests never use the network (CLAUDE.md rules 4 and 6). Real adapters are off by default (`FF_SOURCING_ENABLED_SOURCES=mock,native`, `FF_SOURCING_ADAPTERS` empty) and each has its own kill switch plus the global `FF_SOURCING_KILL_SWITCH`.
- HTTP adapters (`services/sourcing/src/ff_sourcing/adapters/http_base.py`): honest `FactoryFinderBot/...` user agent (validated), robots.txt enforced for `kind=page` (failures fail closed, fetched once per origin), at least 3 s between requests per host (floor enforced in code), caching, cooldown after errors, credentials from the environment only and never printed. No CAPTCHA, login or paywall bypass. Tracking providers follow the same pattern (`FF_TRACKING_HTTP_MIN_INTERVAL_SECONDS`, clamped to >= 3).
- Demand matching (CLAUDE.md rule 7): off by default (`FF_DEMAND_ENABLED=false`), contains no code that sends messages, drafts public replies only, requires human approval, daily cap `FF_DEMAND_DAILY_CAP`, separate publisher switch `FF_DEMAND_PUBLISHER_ENABLED`.
- Tests: `sourcing/tests/test_adversarial_qa3.py` (rate limiter floor, robots rules, fail-closed errors, path tricks), `test_http_provider.py`, `test_licensed_rest.py`, `test_real_adapters.py`, `test_compliance_registry.py` (per-adapter kill switch); `demand/tests/test_compliance_qa.py` (no sending code, approval and kill switch, publisher off by default), `demand/tests/test_security_review.py`.

## 7. Privacy, export and erasure

- `GET /v1/me/export` (authenticated, rate limited with deletion to `FF_GATEWAY_PRIVACY_RATE_LIMIT_PER_MINUTE`, size capped, `Cache-Control: no-store`) returns a JSON bundle: the gateway profile plus what each service holds. A failing service is reported per service, not silently dropped.
- `DELETE /v1/me` requires re-authentication (`password` or `refresh_token` in the body), revokes all sessions, anonymizes the user row, and fans out erasure to every service holding user data. Optional grace period `FF_GATEWAY_DELETION_GRACE_DAYS` (a correct login inside the window cancels it). Per-service work is a durable `deletion_jobs` row retried with backoff by a gateway worker; each step is audited in `account_events`. Admins see jobs at `GET /v1/admin/account-deletions`.
- Internal contract per service: `/v1/internal/users/{id}/export` and `DELETE /v1/internal/users/{id}/data` (not routable from outside; guarded by the internal token). Messaging blanks the user's message text, payments keeps money records (ledger, invoices) by law, and the payer's memo is shown only to the payer.
- Data minimisation: supplier analytics are daily aggregates with no per-viewer rows; retention sweeps (demand 90 d, notifications 180/30 d, payments webhook rows 180 d, sourcing history 400 d, trust reports 365 d and snapshots 730 d; see `docs/RUNBOOK.md` section 5b); logs avoid keys and full PII; verification files are always private (owner or admin or short-lived signed URL).
- Drafts of the policy and terms: `docs/PRIVACY_POLICY.draft.md`, `docs/TERMS.draft.md` (not legal advice, to be reviewed).
- Tests: `gateway/tests/test_account_privacy.py`, `test_private_media.py`; `tests/test_privacy.py` in assistant, demand, feed, freight, media, messaging, notifications, payments, rfq, sourcing, tracking and trust; end-to-end `scripts/e2e_privacy.py`.

## 8. Other controls (where to look)

| Area | Control | Tests / notes |
|---|---|---|
| Money | `Decimal` or decimal strings; wide Decimal context for deal totals; payments ledger status compare-and-set; per-payer invoice caps | `payments/tests/test_security_review*.py`, `rfq/tests/test_security_review*.py` |
| Uploads | magic-byte sniffing, re-encode (metadata stripped), SVG/HTML/PDF refused with 415, decode bombs bounded, per-user quota | `media/tests/test_hardening.py`, `test_adversarial_uploads.py`, `test_private.py` |
| Abuse | anti-spam, report thresholds, account-age gate on reports, per-user caps (offers, shipments, conversations, blocks), prompt-injection guard in the assistant | `feed`, `freight`, `messaging`, `assistant` `test_security_review*.py`, `assistant/tests/test_injection_qa2.py` |
| Input safety | regex `\Z` anchors, bounded cursors, ReDoS caps on provider text | `gateway/tests/test_security_review*.py`, `*/tests/test_security_review_i.py` |
| Supply chain | non-root pinned base image, hardened compose, dependency floors audited with pip-audit | `docs/fixes/supply-chain-review-2026-10.md` |

Known open items (not exhaustive): single shared admin token, registration reveals existing accounts (409), per-process state without Redis, unpinned third-party actions and image digests, unverified real-provider wire shapes. See `docs/fixes/INDEX.md`.
