# gateway (port 8000)

Auth (bcrypt + JWT: access 15 min, refresh 30 days), profile (`/v1/me`), `/v1/home` feed, and a reverse proxy mapping `/v1/*` path prefixes to services (see `ff_gateway/domain/routing.py`). Adds `X-User-Id`, `X-Internal-Token` (if `FF_INTERNAL_TOKEN`), `X-Request-Id`; upstream down -> 502, timeout -> 504. Contract: `contracts/openapi/gateway.yaml`.

Run: `uvicorn ff_gateway.main:app --port 8000`. Test: `../../.venv/bin/python -m pytest -q`.

Env (prefix `FF_GATEWAY_`): `JWT_SECRET` (unset -> ephemeral secret + warning), `DATABASE_URL` (sqlite+aiosqlite:///./gateway.db), `UPSTREAMS` (JSON overrides, e.g. `{"trust":"http://trust:8104"}`), `RATE_LIMIT_PER_MINUTE`, `AUTH_RATE_LIMIT_PER_MINUTE`, `CORS_ORIGINS` (JSON list), `HOME_CLIENT` (http|mock), `ADMIN_TOKEN` (enables `/v1/admin/*`; unset -> 404), `UPSTREAM_TIMEOUT_SECONDS`; plus `FF_INTERNAL_TOKEN`.
Gaps: SMTP adapter is a skeleton (no templates/bounce handling).

## WebSocket proxy

`WS /v1/ws/conversations/{id}` is proxied to messaging (same path). Auth: preferred `?ticket=` from `POST /v1/ws-ticket` (single use, 30 s, `FF_GATEWAY_WS_TICKET_TTL_SECONDS` / `FF_GATEWAY_WS_TICKET_MAX`); legacy `Authorization: Bearer <access>` / `?token=<access>` is **off by default** (`FF_GATEWAY_WS_ALLOW_TOKEN_PARAM=true` re-enables it for pre-ticket app builds; mobile's `chat_socket_provider` already fetches tickets and only falls back to the token against old gateways). Handshakes count in the same per-IP bucket as HTTP (`RATE_LIMIT_PER_MINUTE`, close 4429), `POST /v1/ws-ticket` is limited per user (`WS_TICKET_RATE_LIMIT_PER_MINUTE`, 30, 429) and each user may hold `WS_MAX_CONNECTIONS_PER_USER` (5, 0 = off, per process) open sockets (extra ones close 4429). Only the verified `X-User-Id` / `X-Supplier-Id` (and `X-Internal-Token` if configured) go upstream; client-supplied `user_id` and the token are never forwarded. Close codes: 4401 unauthenticated, 4403/4429 from messaging, 4404 unknown path, 1011 upstream unavailable. Note: access logs of the ASGI server may record `?token=`; prefer the header where possible.

## Supplier claims

`PATCH /v1/me {supplier_id}` records a **pending** claim (`supplier_claim_status`: none|pending|verified); pending/verified ids are unique (409). The gateway forwards `X-Supplier-Id` (HTTP and WS) to messaging only when status is `verified`. Admins (header `X-Admin-Token` == `FF_GATEWAY_ADMIN_TOKEN`, constant-time compare; 404 if unset, 401 if wrong) use `GET /v1/admin/supplier-claims?status=pending|verified`, `POST /v1/admin/supplier-claims/{user_id}/approve|reject`. Reject and `supplier_id: null` release the id and reset status to none. Startup adds the column on existing sqlite DBs; pre-existing claims become pending.

## Admin payments outbox passthrough
`GET /v1/admin/payments/review` (same guards and env vars; `limit` -> `page_size`, `cursor`, `page`, `page_size`; `status` and anything else -> 422) proxies payments `GET /v1/payments/review` and returns its `{items, total, page, page_size}` unchanged; `X-Reviewer` is forwarded sanitized (default `admin`) and the call is logged (`ff_gateway.admin`). Payments down -> 502 `upstream_unavailable`, timeout -> 504.

`GET /v1/admin/payments/outbox` (`status` pending|delivered|dead, `limit` -> payments `page_size`, `cursor`, `page`, `page_size`; any other query param -> 422) and `POST /v1/admin/payments/outbox/{id}/requeue` (id `[A-Za-z0-9_-]{1,64}`, no body). Needs `X-Admin-Token` (= `FF_GATEWAY_ADMIN_TOKEN`; 404 unset, 401 wrong) and the gateway-side `FF_PAYMENTS_ADMIN_TOKEN` (404 when unset), which the gateway injects with the internal token and `X-User-Id: admin`; client identity headers and bodies are never forwarded. Upstream status codes (404 unknown, 409 `not_dead`) pass through.

## Admin demand proxy and console

With the admin token set (404 unset / 401 wrong): `GET /v1/admin/overview` (`pending_supplier_claims`, `pending_drafts` (null if demand is down), `users`) and an allow-listed proxy `/v1/admin/demand/{signals, signals/poll, signals/{id}, drafts, drafts/{id}, drafts/{id}/approve|reject|mark-published|outcome, quota}` -> demand `/v1/...`. Upstream always gets `X-User-Id: admin` and `X-Internal-Token`; client identity headers (incl. X-Admin-Token, Authorization) are never forwarded. Upstream `demand` defaults to `http://localhost:8110` (add it to `FF_GATEWAY_UPSTREAMS` in docker-compose).
`FF_GATEWAY_SERVE_ADMIN=true` serves `apps/admin` at `/admin/` (default off; `FF_GATEWAY_ADMIN_DIR` overrides the folder). CORS stays closed: a separately hosted admin page must be listed in `FF_GATEWAY_CORS_ORIGINS`.

## Security notes
- Refresh tokens are single-use and tracked in `refresh_tokens` (hashed jti + family). Reusing a rotated token revokes the family; `POST /v1/auth/logout` revokes it explicitly.
- CORS: no origins allowed unless `FF_GATEWAY_CORS_ORIGINS` (JSON list) is set.
- WebSocket auth uses `?ticket=` (default); the `?token=` fallback is opt-in (`FF_GATEWAY_WS_ALLOW_TOKEN_PARAM`), uvicorn access logs are redacted, any proxy in front must scrub it too.
- Verified `X-Supplier-Id` (admin-verified claims only) is forwarded to messaging and rfq; client-sent values are never forwarded.

## Email verification
`POST /v1/auth/verify-email {token}` (204; generic 400 for unknown/expired/used/stale tokens) and `POST /v1/auth/resend-verification {email}` (always 202, same body for unknown/verified/known accounts; silently throttled to `RESEND_VERIFICATION_PER_MINUTE` per address on top of the auth IP limit). Tokens are random (`token_urlsafe(32)`), stored only as SHA-256 in `email_verification_tokens`, single use, TTL `EMAIL_VERIFICATION_TTL_SECONDS` (24 h), bound to the address they were issued for (changing `email` via `PATCH /v1/me` resets `email_verified` and mails the new address). `MeOut.email_verified` is additive. Mail goes through `domain/mail.py`: `FF_GATEWAY_MAIL_BACKEND=off` (default: nothing sent, no tokens issued), `mock` (in-memory `app.state.mailer.outbox`, for tests), `smtp` (`SMTP_HOST/PORT/USER/PASSWORD/STARTTLS`, `MAIL_FROM`, optional `VERIFY_URL_TEMPLATE` with `{token}`). `FF_GATEWAY_REQUIRE_EMAIL_VERIFIED=true` (default false) makes payments writes, new supplier claims (`PATCH /v1/me supplier_id`) and `/v1/my/*` writes answer 403 `email_not_verified`; phone-only accounts stay unverified, so enable it only with mail on.

## Password reset and change
- `POST /v1/auth/password/forgot {email}`: always 202 `{"status":"accepted"}`, identical for unknown/disabled/known accounts and when mail is off. Lookup, token and mail happen after the response (no timing oracle). Token: `token_urlsafe(32)`, only SHA-256 in `password_reset_tokens`, TTL `PASSWORD_RESET_TTL_SECONDS` (1800), a newer request drops older tokens. Silent throttle (still 202) per email+IP (`PASSWORD_FORGOT_PER_MINUTE`, 1) and per email (`PASSWORD_FORGOT_PER_EMAIL_PER_MINUTE`, 3); the per-IP auth limit gives 429. Mail via `domain/mail.py` (needs `MAIL_BACKEND` mock|smtp; optional `PASSWORD_RESET_URL_TEMPLATE` with `{token}`).
- `POST /v1/auth/password/reset {token, new_password}`: 204; unknown/expired/used token -> generic 400 `invalid_reset_token`; weak password -> 422 and the token is kept; success sets the hash, marks the token used (atomic) and revokes every refresh token of the user.
- `POST /v1/me/password {current_password, new_password}` (bearer): wrong current -> 403 `reauth_failed` (failures throttled per user via `LOGIN_FAIL_LIMIT_PER_MINUTE`, then 429); revokes all refresh tokens and returns a fresh `Tokens` pair for this device. Other sessions' access tokens stop working immediately (token version, below).
- `PATCH /v1/me` with a changed/removed `email` needs `current_password` (422 missing, 403 wrong); the old address gets a notice mail.

## Access-token revocation (`tv`)
`users.token_version` (int, default 0; the column is added on startup to existing DBs like the other additive columns) is carried in access tokens as claim `tv`. Everywhere the user row is re-checked (native routes via `current_user`, the proxy's `is_active` cache (<= 5 s, per process), `DELETE /v1/me`, ws handshakes using `?token=`) a mismatching `tv` answers 401 `invalid_token`. Tokens without `tv` (issued before this change) are accepted only while the user's version is 0. The version is bumped (atomically, `SET token_version = token_version + 1`) on password change, password reset, `POST /v1/auth/logout-all` and account deactivation/deletion (so cancelling a deletion by logging in does not revive old tokens). `POST /v1/auth/logout-all` (bearer, 204) revokes every refresh token and bumps the version. Residual: a ws ticket minted just before a bump stays valid for its 30 s TTL; other replicas' `is_active` caches lag up to 5 s.

## Redis-backed ws tickets and socket counters
With `FF_GATEWAY_REDIS_URL` (alias `FF_REDIS_URL`) set the same Redis client that backs the rate limiter also stores ws tickets (`SET ... EX ttl` / `GETDEL`, key `ff:gw:wst:*`, Redis >= 6.2) and the per-user open-socket counters (`INCR`/`DECR`, `ff:gw:wsc:<user>`, safety TTL 6 h refreshed on every connect), so several replicas share them. Without it (or if Redis is unreachable at runtime, logged once per outage) the in-memory implementations in `domain/ws_tickets.py` are used. Tests inject a fake client (`create_app(redis_client=...)`); no network.

## Upstream resilience (proxy)
- Timeouts/pool: `UPSTREAM_CONNECT_TIMEOUT_SECONDS` (3), `UPSTREAM_TIMEOUT_SECONDS` (15, read/write), `UPSTREAM_POOL_TIMEOUT_SECONDS` (5), `UPSTREAM_MAX_CONNECTIONS` (200), `UPSTREAM_MAX_KEEPALIVE_CONNECTIONS` (50); one shared pool, so a slow service can no longer hold all connections for ever (pool wait -> 504).
- Circuit breaker per upstream (`domain/circuit_breaker.py`): `BREAKER_FAILURE_THRESHOLD` (5, 0 = off) consecutive failures (connect error, timeout, upstream 502/503/504) open it for `BREAKER_COOLDOWN_SECONDS` (30); while open the proxy answers 503 `upstream_unavailable` (`details.circuit=open`) with `Retry-After` without calling the service; after the cooldown exactly one half-open probe goes through (others keep failing fast), success closes, failure reopens. 4xx and plain 500 do not count; any success resets the streak. State is per process. Applies to proxied HTTP routes only (not ws, privacy fan-out or `/ready`).

## Ops (logging / readiness / rate limits)
- `GET /ready`: 503 if the database is down; otherwise 200 with `checks` and `upstreams` as `{name: up|down boolean}` only (no URLs; probed via each upstream `/health`, cached 5 s). `status` is `degraded` when any upstream is down.
- Logs: one JSON line per HTTP request (`FF_LOG_FORMAT=text` for dev); `X-Request-Id` is accepted (sanitised) or generated, returned, and forwarded to upstreams. Path is the route template (proxied routes log as `/v1/<prefix>/*`); query strings, tokens and Authorization are never logged. `user_id` comes only from the verified JWT, never from client headers.
- Client IP: `FF_GATEWAY_TRUSTED_PROXIES` (comma-separated CIDRs/IPs, default empty). `X-Forwarded-For` is used only when the direct peer is in that list (right-most non-proxy hop); otherwise the peer. Invalid CIDRs fail startup.
- Register enumeration: `POST /v1/auth/register` keeps its 409 `account_exists` (contract unchanged) but is throttled per client IP, `FF_GATEWAY_REGISTER_PER_HOUR` (default 10, 0 = off, 429 with `Retry-After`; counted for every attempt, shared via Redis if configured) and always hashes the password before looking the identifier up, so new/existing responses take similar time. See `docs/decisions/gateway-register-enumeration.md`.
- Limits: `RATE_LIMIT_PER_MINUTE`/`AUTH_RATE_LIMIT_PER_MINUTE` per IP, plus `USER_WRITE_RATE_LIMIT_PER_MINUTE` (default 120, 0 = off) per verified user on POST/PUT/PATCH/DELETE outside `/v1/auth`. Limiter memory is capped by `RATE_LIMIT_MAX_KEYS` (default 50000; expired windows swept, oldest evicted). Rate-limit storage is pluggable (`domain/rate_limit.py`): in-memory by default (per process); set `FF_GATEWAY_REDIS_URL` (and install the `redis` extra) to share counters across replicas. The redis library is imported lazily; if it is missing or Redis is down the gateway logs a warning and counts in memory instead.

## Trust verification, freight and feed admin
- `/v1/trust/verification/*` (supplier documents): bearer token required, plus a **verified supplier claim** (403 `supplier_claim_required` otherwise). `X-Supplier-Id` comes from the DB, never the client. Non-GET needs a verified email when `FF_GATEWAY_REQUIRE_EMAIL_VERIFIED` is on; JSON body max 64 KiB.
- `GET /v1/trust/suppliers/{id}/verification` (badge) is public; everything else under `/v1/trust` stays authenticated.
- Admin passthroughs (`api/admin_services.py`): `/v1/admin/trust/verification/*` (documents list, decision, expiry, audit), `/v1/admin/freight/*`, `/v1/admin/feed/*`. Allow-listed (method, path) pairs only (else 404), path ids `[A-Za-z0-9_-]{1,64}`, query allow-list (else 422), body <= 256 KiB. Need `X-Admin-Token` (= `FF_GATEWAY_ADMIN_TOKEN`; 404 unset, 401 wrong) and the gateway-side `FF_TRUST_ADMIN_TOKEN` / `FF_FREIGHT_ADMIN_TOKEN` / `FF_FEED_ADMIN_TOKEN` (404 when unset), injected with the internal token, `X-User-Id: admin` (and `X-Reviewer: admin` for trust). Client identity/admin headers are never forwarded.

## Account deletion and data export (store requirements)
`DELETE /v1/me` (body `{"password"}` or `{"refresh_token"}`) revokes every session, anonymizes the user row (id kept) and erases/anonymizes the user's data in all services through durable `deletion_jobs` (retried with backoff by a background loop; `GET /v1/admin/account-deletions` lists open ones). `GET /v1/me/export` streams a size-capped JSON bundle of the profile plus every service's export, reporting failures per service. Both are rate limited per user. Settings: `FF_GATEWAY_DELETION_GRACE_DAYS` (0), `PRIVACY_RATE_LIMIT_PER_MINUTE` (3), `PRIVACY_TIMEOUT_SECONDS` (10), `EXPORT_MAX_BYTES` (5 MiB), `DELETION_MAX_ATTEMPTS` (12), `DELETION_WORKER_INTERVAL_SECONDS` (60). Services expose `POST /v1/internal/users/{id}/export` and `DELETE /v1/internal/users/{id}/data` (internal token, 404 otherwise); the gateway does not route `/v1/internal/*`. Retention exceptions: `docs/decisions/account-deletion.md`.

## Environment reference (complete)
Every setting in `src/ff_gateway/config.py` (`Settings`, case-insensitive env names). Secrets are never defaulted.

| Variable | Default |
|---|---|
| `FF_GATEWAY_JWT_SECRET` | unset |
| `FF_GATEWAY_JWT_ALGORITHM` | HS256 |
| `FF_GATEWAY_ACCESS_TTL_SECONDS` | 900 |
| `FF_GATEWAY_REFRESH_TTL_SECONDS` | 2592000 |
| `FF_GATEWAY_DATABASE_URL` | sqlite+aiosqlite:///./gateway.db |
| `FF_GATEWAY_UPSTREAMS` | {} |
| `FF_INTERNAL_TOKEN` | unset |
| `FF_SOURCING_ADMIN_TOKEN` | unset |
| `FF_MEDIA_ADMIN_TOKEN` | unset |
| `FF_PAYMENTS_ADMIN_TOKEN` | unset |
| `FF_TRUST_ADMIN_TOKEN` | unset |
| `FF_FREIGHT_ADMIN_TOKEN` | unset |
| `FF_FEED_ADMIN_TOKEN` | unset |
| `FF_GATEWAY_UPSTREAM_TIMEOUT_SECONDS` | 15.0 |
| `FF_GATEWAY_UPSTREAM_CONNECT_TIMEOUT_SECONDS` | 3.0 |
| `FF_GATEWAY_UPSTREAM_POOL_TIMEOUT_SECONDS` | 5.0 |
| `FF_GATEWAY_UPSTREAM_MAX_CONNECTIONS` | 200 |
| `FF_GATEWAY_UPSTREAM_MAX_KEEPALIVE_CONNECTIONS` | 50 |
| `FF_GATEWAY_BREAKER_FAILURE_THRESHOLD` | 5 (0 = off) |
| `FF_GATEWAY_BREAKER_COOLDOWN_SECONDS` | 30.0 |
| `FF_GATEWAY_REDIS_URL` / `FF_REDIS_URL` | unset (memory); also backs ws tickets + socket counters |
| `FF_GATEWAY_WS_TICKET_TTL_SECONDS` | 30 |
| `FF_GATEWAY_WS_TICKET_MAX` | 10000 |
| `FF_GATEWAY_WS_ALLOW_TOKEN_PARAM` | False |
| `FF_GATEWAY_WS_MAX_CONNECTIONS_PER_USER` | 5 (0 = off) |
| `FF_GATEWAY_WS_TICKET_RATE_LIMIT_PER_MINUTE` | 30 (0 = off) |
| `FF_GATEWAY_PASSWORD_RESET_TTL_SECONDS` | 1800 |
| `FF_GATEWAY_PASSWORD_FORGOT_PER_MINUTE` | 1 (per email+IP) |
| `FF_GATEWAY_PASSWORD_FORGOT_PER_EMAIL_PER_MINUTE` | 3 |
| `FF_GATEWAY_PASSWORD_RESET_URL_TEMPLATE` | unset |
| `FF_GATEWAY_MAX_BODY_BYTES` | 10485760 |
| `FF_GATEWAY_JSON_MAX_BODY_BYTES` | 1048576 (cap for every non-media route; MAX_BODY_BYTES applies to `/v1/media`) |
| `FF_GATEWAY_BODY_READ_TIMEOUT_SECONDS` | 30 (whole body must arrive; media: `FF_GATEWAY_MEDIA_BODY_READ_TIMEOUT_SECONDS` 120) |
| `FF_GATEWAY_LOGIN_FAIL_LIMIT_PER_MINUTE` | 10 (failed passwords per account per minute, then 429) |
| `FF_GATEWAY_JWT_SECRET_PREVIOUS` | unset (verify-only key during rotation) |
| `FF_GATEWAY_RATE_LIMIT_PER_MINUTE` | 300 |
| `FF_GATEWAY_MEDIA_RATE_LIMIT_PER_MINUTE` | 3000 |
| `FF_GATEWAY_USER_WRITE_RATE_LIMIT_PER_MINUTE` | 120 |
| `FF_GATEWAY_RATE_LIMIT_MAX_KEYS` | 50000 |
| `FF_GATEWAY_TRUSTED_PROXIES` | unset |
| `FF_GATEWAY_AUTH_RATE_LIMIT_PER_MINUTE` | 30 |
| `FF_GATEWAY_ADMIN_FAIL_LIMIT_PER_MINUTE` | 20 (failed `/v1/admin/*` token attempts per IP before 429) |
| `FF_GATEWAY_CORS_ORIGINS` | [] |
| `FF_GATEWAY_ADMIN_TOKEN` | unset |
| `FF_GATEWAY_SERVE_ADMIN` | False |
| `FF_GATEWAY_ADMIN_DIR` | unset |
| `FF_GATEWAY_HOME_CLIENT` | http |
| `FF_GATEWAY_BCRYPT_ROUNDS` | 12 |
| `FF_GATEWAY_REDIS_URL` | unset |
| `FF_GATEWAY_REQUIRE_EMAIL_VERIFIED` | False |
| `FF_GATEWAY_EMAIL_VERIFICATION_TTL_SECONDS` | 86400 |
| `FF_GATEWAY_RESEND_VERIFICATION_PER_MINUTE` | 1 |
| `FF_GATEWAY_MAIL_BACKEND` | off |
| `FF_GATEWAY_MAIL_FROM` | no-reply@localhost |
| `FF_GATEWAY_SMTP_HOST` | unset |
| `FF_GATEWAY_SMTP_PORT` | 587 |
| `FF_GATEWAY_SMTP_USER` | unset |
| `FF_GATEWAY_SMTP_PASSWORD` | unset |
| `FF_GATEWAY_SMTP_STARTTLS` | True |
| `FF_GATEWAY_VERIFY_URL_TEMPLATE` | unset |
| `FF_GATEWAY_DELETION_GRACE_DAYS` | 0 |
| `FF_GATEWAY_PRIVACY_RATE_LIMIT_PER_MINUTE` | 3 |
| `FF_GATEWAY_PRIVACY_TIMEOUT_SECONDS` | 10.0 |
| `FF_GATEWAY_EXPORT_MAX_BYTES` | 5242880 |
| `FF_GATEWAY_DELETION_MAX_ATTEMPTS` | 12 |
| `FF_GATEWAY_DELETION_WORKER_INTERVAL_SECONDS` | 60.0 |

Also read from the environment: `FF_LOG_FORMAT` (`text` for dev; JSON by default), `FF_ENV=production` refuses to start unless `FF_GATEWAY_JWT_SECRET` and `FF_GATEWAY_ADMIN_TOKEN` are set (see `docs/OPS.md`).
