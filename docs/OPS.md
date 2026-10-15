# Operations notes

## Probes
- Liveness: `GET /health` on every service. Readiness: `GET /ready` (200 ready / 503 unavailable; checks DB where one exists). Neither needs the internal token.
- Gateway `/ready` also returns `upstreams: {name: bool}`; status `degraded` (HTTP 200) if a backend is down, 503 only when the gateway DB is down.

## Logs
- One JSON line per request on stdout: `ts, level, service, request_id, method, path, status, duration_ms, user_id`. `FF_LOG_FORMAT=text` for local dev.
- Correlate by `request_id`: the gateway accepts/generates `X-Request-Id` and forwards it to every upstream, which echo it in responses and logs.
- Never logged: query strings, Authorization, tokens, bodies. (WebSocket `?token=` is also redacted in uvicorn access logs; scrub it in any extra proxy.)

## Gateway behind a proxy / LB
- Set `FF_GATEWAY_TRUSTED_PROXIES` to the proxy CIDRs (e.g. `10.0.0.0/8,172.16.0.0/12`); otherwise all clients share the proxy's IP for rate limiting. Do not include untrusted networks: anyone in the list can spoof `X-Forwarded-For`.
- Limits (env, prefix `FF_GATEWAY_`): `RATE_LIMIT_PER_MINUTE` (300), `AUTH_RATE_LIMIT_PER_MINUTE` (30), `USER_WRITE_RATE_LIMIT_PER_MINUTE` (120, 0 off), `RATE_LIMIT_MAX_KEYS` (50000).
- The limiter is in-memory per process; with N replicas the effective limit is N x. Move to Redis before scaling out.

## Production mode guard (`FF_ENV=production`)
Opt-in, fail closed. Default behaviour (variable unset or any other value) is unchanged.
- rfq, payments, notifications, sourcing, tracking, messaging, media, feed, freight: refuse to start (`RuntimeError` in `create_app`) if `FF_INTERNAL_TOKEN` is unset/empty.
- trust: refuses to start (`RuntimeError` in `create_app`) if `FF_TRUST_VERIFICATION_HASH_KEY` is unset (keyed duplicate detection for verification documents must survive restarts); startup also aborts if the key differs from the one the stored fingerprints were made with.
- gateway: refuses to start if `FF_GATEWAY_JWT_SECRET` or `FF_GATEWAY_ADMIN_TOKEN` is missing.
- Implemented per service as a tiny duplicated helper (`_require_production_token`), no cross-service imports. Tests: `tests/test_production_guard.py` in each service.
- Gateway `/v1/admin/payments/outbox*` needs `FF_PAYMENTS_ADMIN_TOKEN` set on the gateway too (same value as the payments service's); unset = those routes answer 404.
- Gateway `/v1/admin/trust/verification/*`, `/v1/admin/freight/*` and `/v1/admin/feed/*` (admin console passthroughs) need `FF_TRUST_ADMIN_TOKEN`, `FF_FREIGHT_ADMIN_TOKEN` and `FF_FEED_ADMIN_TOKEN` set on the gateway too (same values as each service's); unset = 404. All three default to empty in `docker-compose.yml` and `.env.example`.
- Gateway also re-checks `is_active` on every proxied request (cached 5 s), so disabling a user takes effect within ~5 s instead of at access-token expiry.

## Trust persistence
`FF_TRUST_DATABASE_URL` (default SQLite `./data/trust.db`; in Docker that is inside the container, so mount a volume at `/app/data` or use PostgreSQL, otherwise a recreated container starts empty). Run `alembic upgrade head` in `services/trust` before starting on PostgreSQL. `/ready` returns 503 when the database is unreachable. The audit table is append-only by trigger: do not grant UPDATE/DELETE to the application role either.

## Account deletion and data export
Details and the retention exceptions (payments ledger, rfq deals, trust verification audit, counterparty records): `docs/decisions/account-deletion.md`.
- `DELETE /v1/me` (re-auth by password or refresh token) and `GET /v1/me/export` on the gateway; both rate limited per user (`FF_GATEWAY_PRIVACY_RATE_LIMIT_PER_MINUTE`, default 3).
- Settings (prefix `FF_GATEWAY_`): `DELETION_GRACE_DAYS` (0), `PRIVACY_TIMEOUT_SECONDS` (10), `EXPORT_MAX_BYTES` (5 MiB), `DELETION_MAX_ATTEMPTS` (12), `DELETION_WORKER_INTERVAL_SECONDS` (60, 0 turns the retry loop off).
- Every service needs the same `FF_INTERNAL_TOKEN` as the gateway: the internal export/erase routes answer 404 otherwise, the gateway then records `http_404` and retries until the job is dead. The upstream map (`FF_GATEWAY_UPSTREAMS`) must include every service.
- Failed erasures: `GET /v1/admin/account-deletions?status=pending|dead` (admin token). `dead` jobs need a human: fix the cause, then reset the row (`UPDATE deletion_jobs SET status='pending', attempts=0 WHERE ...`). Do not delete jobs.
- The tables `deletion_jobs` and `account_events` are in the gateway DB. They hold opaque ids, service names and short error codes, no PII. Back them up with the gateway DB.
- Logs: audit lines (`"event":"audit"`) have the opaque user id and request id only.
- Ledger and audit records are retained on purpose; do not "clean" payments or rfq deal tables when a user is deleted.

