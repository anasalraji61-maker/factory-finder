# gateway (port 8000)

Auth (bcrypt + JWT: access 15 min, refresh 30 days), profile (`/v1/me`), `/v1/home` feed, and a reverse proxy mapping `/v1/*` path prefixes to services (see `ff_gateway/domain/routing.py`). Adds `X-User-Id`, `X-Internal-Token` (if `FF_INTERNAL_TOKEN`), `X-Request-Id`; upstream down -> 502, timeout -> 504. Contract: `contracts/openapi/gateway.yaml`.

Run: `uvicorn ff_gateway.main:app --port 8000`. Test: `../../.venv/bin/python -m pytest -q`.

Env (prefix `FF_GATEWAY_`): `JWT_SECRET` (unset -> ephemeral secret + warning), `DATABASE_URL` (sqlite+aiosqlite:///./gateway.db), `UPSTREAMS` (JSON overrides, e.g. `{"trust":"http://trust:8104"}`), `RATE_LIMIT_PER_MINUTE`, `AUTH_RATE_LIMIT_PER_MINUTE`, `CORS_ORIGINS` (JSON list), `HOME_CLIENT` (http|mock), `ADMIN_TOKEN` (enables `/v1/admin/*`; unset -> 404), `UPSTREAM_TIMEOUT_SECONDS`; plus `FF_INTERNAL_TOKEN`.
Gaps: SMTP adapter is a skeleton (no templates/bounce handling).

## WebSocket proxy

`WS /v1/ws/conversations/{id}` is proxied to messaging (same path). Auth: preferred `?ticket=` from `POST /v1/ws-ticket` (single use, 30 s, `FF_GATEWAY_WS_TICKET_TTL_SECONDS` / `FF_GATEWAY_WS_TICKET_MAX`); legacy `Authorization: Bearer <access>` or `?token=<access>` stays accepted while `FF_GATEWAY_WS_ALLOW_TOKEN_PARAM=true` (default). Only the verified `X-User-Id` / `X-Supplier-Id` (and `X-Internal-Token` if configured) go upstream; client-supplied `user_id` and the token are never forwarded. Close codes: 4401 unauthenticated, 4403/4429 from messaging, 4404 unknown path, 1011 upstream unavailable. Note: access logs of the ASGI server may record `?token=`; prefer the header where possible.

## Supplier claims

`PATCH /v1/me {supplier_id}` records a **pending** claim (`supplier_claim_status`: none|pending|verified); pending/verified ids are unique (409). The gateway forwards `X-Supplier-Id` (HTTP and WS) to messaging only when status is `verified`. Admins (header `X-Admin-Token` == `FF_GATEWAY_ADMIN_TOKEN`, constant-time compare; 404 if unset, 401 if wrong) use `GET /v1/admin/supplier-claims?status=pending|verified`, `POST /v1/admin/supplier-claims/{user_id}/approve|reject`. Reject and `supplier_id: null` release the id and reset status to none. Startup adds the column on existing sqlite DBs; pre-existing claims become pending.

## Admin payments outbox passthrough
`GET /v1/admin/payments/outbox` (`status` pending|delivered|dead, `limit` -> payments `page_size`, `cursor`, `page`, `page_size`; any other query param -> 422) and `POST /v1/admin/payments/outbox/{id}/requeue` (id `[A-Za-z0-9_-]{1,64}`, no body). Needs `X-Admin-Token` (= `FF_GATEWAY_ADMIN_TOKEN`; 404 unset, 401 wrong) and the gateway-side `FF_PAYMENTS_ADMIN_TOKEN` (404 when unset), which the gateway injects with the internal token and `X-User-Id: admin`; client identity headers and bodies are never forwarded. Upstream status codes (404 unknown, 409 `not_dead`) pass through.

## Admin demand proxy and console

With the admin token set (404 unset / 401 wrong): `GET /v1/admin/overview` (`pending_supplier_claims`, `pending_drafts` (null if demand is down), `users`) and an allow-listed proxy `/v1/admin/demand/{signals, signals/poll, signals/{id}, drafts, drafts/{id}, drafts/{id}/approve|reject|mark-published|outcome, quota}` -> demand `/v1/...`. Upstream always gets `X-User-Id: admin` and `X-Internal-Token`; client identity headers (incl. X-Admin-Token, Authorization) are never forwarded. Upstream `demand` defaults to `http://localhost:8110` (add it to `FF_GATEWAY_UPSTREAMS` in docker-compose).
`FF_GATEWAY_SERVE_ADMIN=true` serves `apps/admin` at `/admin/` (default off; `FF_GATEWAY_ADMIN_DIR` overrides the folder). CORS stays closed: a separately hosted admin page must be listed in `FF_GATEWAY_CORS_ORIGINS`.

## Security notes
- Refresh tokens are single-use and tracked in `refresh_tokens` (hashed jti + family). Reusing a rotated token revokes the family; `POST /v1/auth/logout` revokes it explicitly.
- CORS: no origins allowed unless `FF_GATEWAY_CORS_ORIGINS` (JSON list) is set.
- WebSocket auth accepts `?token=<access jwt>` (clients cannot set headers); uvicorn access logs are redacted, any proxy in front must scrub it too.
- Verified `X-Supplier-Id` (admin-verified claims only) is forwarded to messaging and rfq; client-sent values are never forwarded.

## Email verification
`POST /v1/auth/verify-email {token}` (204; generic 400 for unknown/expired/used/stale tokens) and `POST /v1/auth/resend-verification {email}` (always 202, same body for unknown/verified/known accounts; silently throttled to `RESEND_VERIFICATION_PER_MINUTE` per address on top of the auth IP limit). Tokens are random (`token_urlsafe(32)`), stored only as SHA-256 in `email_verification_tokens`, single use, TTL `EMAIL_VERIFICATION_TTL_SECONDS` (24 h), bound to the address they were issued for (changing `email` via `PATCH /v1/me` resets `email_verified` and mails the new address). `MeOut.email_verified` is additive. Mail goes through `domain/mail.py`: `FF_GATEWAY_MAIL_BACKEND=off` (default: nothing sent, no tokens issued), `mock` (in-memory `app.state.mailer.outbox`, for tests), `smtp` (`SMTP_HOST/PORT/USER/PASSWORD/STARTTLS`, `MAIL_FROM`, optional `VERIFY_URL_TEMPLATE` with `{token}`). `FF_GATEWAY_REQUIRE_EMAIL_VERIFIED=true` (default false) makes payments writes, new supplier claims (`PATCH /v1/me supplier_id`) and `/v1/my/*` writes answer 403 `email_not_verified`; phone-only accounts stay unverified, so enable it only with mail on.

## Ops (logging / readiness / rate limits)
- `GET /ready`: 503 if the database is down; otherwise 200 with `checks` and `upstreams` as `{name: up|down boolean}` only (no URLs; probed via each upstream `/health`, cached 5 s). `status` is `degraded` when any upstream is down.
- Logs: one JSON line per HTTP request (`FF_LOG_FORMAT=text` for dev); `X-Request-Id` is accepted (sanitised) or generated, returned, and forwarded to upstreams. Path is the route template (proxied routes log as `/v1/<prefix>/*`); query strings, tokens and Authorization are never logged. `user_id` comes only from the verified JWT, never from client headers.
- Client IP: `FF_GATEWAY_TRUSTED_PROXIES` (comma-separated CIDRs/IPs, default empty). `X-Forwarded-For` is used only when the direct peer is in that list (right-most non-proxy hop); otherwise the peer. Invalid CIDRs fail startup.
- Limits: `RATE_LIMIT_PER_MINUTE`/`AUTH_RATE_LIMIT_PER_MINUTE` per IP, plus `USER_WRITE_RATE_LIMIT_PER_MINUTE` (default 120, 0 = off) per verified user on POST/PUT/PATCH/DELETE outside `/v1/auth`. Limiter memory is capped by `RATE_LIMIT_MAX_KEYS` (default 50000; expired windows swept, oldest evicted). Rate-limit storage is pluggable (`domain/rate_limit.py`): in-memory by default (per process); set `FF_GATEWAY_REDIS_URL` (and install the `redis` extra) to share counters across replicas. The redis library is imported lazily; if it is missing or Redis is down the gateway logs a warning and counts in memory instead.

## Trust verification, freight and feed admin
- `/v1/trust/verification/*` (supplier documents): bearer token required, plus a **verified supplier claim** (403 `supplier_claim_required` otherwise). `X-Supplier-Id` comes from the DB, never the client. Non-GET needs a verified email when `FF_GATEWAY_REQUIRE_EMAIL_VERIFIED` is on; JSON body max 64 KiB.
- `GET /v1/trust/suppliers/{id}/verification` (badge) is public; everything else under `/v1/trust` stays authenticated.
- Admin passthroughs (`api/admin_services.py`): `/v1/admin/trust/verification/*` (documents list, decision, expiry, audit), `/v1/admin/freight/*`, `/v1/admin/feed/*`. Allow-listed (method, path) pairs only (else 404), path ids `[A-Za-z0-9_-]{1,64}`, query allow-list (else 422), body <= 256 KiB. Need `X-Admin-Token` (= `FF_GATEWAY_ADMIN_TOKEN`; 404 unset, 401 wrong) and the gateway-side `FF_TRUST_ADMIN_TOKEN` / `FF_FREIGHT_ADMIN_TOKEN` / `FF_FEED_ADMIN_TOKEN` (404 when unset), injected with the internal token, `X-User-Id: admin` (and `X-Reviewer: admin` for trust). Client identity/admin headers are never forwarded.

## Account deletion and data export (store requirements)
`DELETE /v1/me` (body `{"password"}` or `{"refresh_token"}`) revokes every session, anonymizes the user row (id kept) and erases/anonymizes the user's data in all services through durable `deletion_jobs` (retried with backoff by a background loop; `GET /v1/admin/account-deletions` lists open ones). `GET /v1/me/export` streams a size-capped JSON bundle of the profile plus every service's export, reporting failures per service. Both are rate limited per user. Settings: `FF_GATEWAY_DELETION_GRACE_DAYS` (0), `PRIVACY_RATE_LIMIT_PER_MINUTE` (3), `PRIVACY_TIMEOUT_SECONDS` (10), `EXPORT_MAX_BYTES` (5 MiB), `DELETION_MAX_ATTEMPTS` (12), `DELETION_WORKER_INTERVAL_SECONDS` (60). Services expose `POST /v1/internal/users/{id}/export` and `DELETE /v1/internal/users/{id}/data` (internal token, 404 otherwise); the gateway does not route `/v1/internal/*`. Retention exceptions: `docs/decisions/account-deletion.md`.

