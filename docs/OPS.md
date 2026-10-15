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
- Gateway `/v1/admin/moderation/*` (sourcing, `FF_SOURCING_ADMIN_TOKEN`) and `/v1/admin/media/files/{name}` (media, `FF_MEDIA_ADMIN_TOKEN`; read-only, no listing) follow the same rule: the token must be set on the gateway and on the service with the same value, else 404. `/v1/admin/demand/*`, `/v1/admin/supplier-claims*`, `/v1/admin/overview` and `/v1/admin/account-deletions` need only `FF_GATEWAY_ADMIN_TOKEN` (demand also needs the internal token to match).
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


## Retention and limits
Defaults come from each service's `config.py` (full tables in each `services/<svc>/README.md`). A retention value of `0` turns that rule off where noted. Purges only remove inert data; ledgers, deals and audit trails are kept on purpose.

| Service | Setting (default) | What is purged / when it runs |
|---|---|---|
| demand | `FF_DEMAND_SIGNAL_RETENTION_DAYS` (90), `FF_DEMAND_REJECTED_DRAFT_RETENTION_DAYS` (90); 0 = off | Old signals and rejected drafts; runs after each `POST /v1/signals/poll`. Approved and published drafts are kept. |
| notifications | `FF_NOTIFICATIONS_ALERT_RETENTION_DAYS` (180), `FF_NOTIFICATIONS_DELIVERY_RETENTION_DAYS` (30) | Old alerts and delivery rows; runs only inside the scheduler loop, so it needs `FF_NOTIFICATIONS_SCHEDULER_ENABLED=true` (interval `FF_NOTIFICATIONS_SCHEDULER_INTERVAL_SECONDS`, 900). |
| payments | `FF_PAYMENTS_WEBHOOK_EVENT_RETENTION_DAYS` (180), `FF_PAYMENTS_OUTBOX_DELIVERED_RETENTION_DAYS` (180), `FF_PAYMENTS_ATTEMPT_RETENTION_DAYS` (365); 0 = off | Webhook replay rows, delivered outbox events, attempts of expired/failed invoices; runs in `POST /v1/payments/sweep`. Invoices, ledger, paid/refunded history and pending/dead outbox events are never deleted. |
| sourcing | `FF_SOURCING_PRICE_HISTORY_RETENTION_DAYS` (400), `FF_SOURCING_ANALYTICS_RETENTION_DAYS` (400) | Price observations and daily analytics counters. |
| trust | `FF_TRUST_REPORT_RETENTION_DAYS` (365), `FF_TRUST_SNAPSHOT_RETENTION_DAYS` (730) | Rejected and stale pending reports, and score snapshots; at startup and at most hourly on writes. Accepted reports and the verification audit are kept. |

Per-user and abuse limits (all env-tunable, 0 disables where the service README says so):
- gateway: `FF_GATEWAY_RATE_LIMIT_PER_MINUTE` (300 per IP), `AUTH_RATE_LIMIT_PER_MINUTE` (30), `USER_WRITE_RATE_LIMIT_PER_MINUTE` (120), `MEDIA_RATE_LIMIT_PER_MINUTE` (3000), `MAX_BODY_BYTES` (10 MiB), `PRIVACY_RATE_LIMIT_PER_MINUTE` (3).
- media: `FF_MEDIA_MAX_UPLOAD_BYTES` (5 MiB), `MAX_FILES_PER_USER` (200), `MAX_UPLOADS_PER_HOUR` (30), `MAX_DIMENSION` (8000), `MAX_PIXELS` (40 000 000).
- payments: `FF_PAYMENTS_MAX_OPEN_INVOICES_PER_USER` (20), `MAX_INVOICES_PER_USER_PER_DAY` (50).
- sourcing: `FF_SOURCING_MAX_LISTINGS_PER_SUPPLIER` (200), `CREATE_RATE_PER_HOUR` (30), `REPORT_RATE_PER_HOUR` (10).
- feed: `FF_FEED_MAX_POSTS_PER_SUPPLIER` (500), `MAX_FOLLOWS_PER_USER` (500), `MAX_COMMENTS_PER_POST` (1000), hourly `RATE_POSTS` (10), `RATE_COMMENTS` (30), `RATE_LIKES` (200), `RATE_FOLLOWS` (60), `RATE_REPORTS` (20).
- freight: `FF_FREIGHT_MAX_OPEN_REQUESTS_PER_BUYER` (50), `MAX_QUOTES_PER_REQUEST` (50), `MAX_LANES_PER_FORWARDER` (50), `MAX_APPLICATIONS_PER_USER` (5), hourly `RATE_APPLICATIONS` (3), `RATE_REQUESTS` (10), `RATE_QUOTES` (60), `RATE_RATINGS` (20), `RATE_REPORTS` (20).
- notifications: `FF_NOTIFICATIONS_MAX_WATCHES_PER_USER` (100), `MAX_ALERTS_PER_USER` (1000), `MAX_DEVICES_PER_USER` (10).
- assistant: `FF_ASSISTANT_QUOTA_PER_DAY` (200), `ANON_QUOTA_PER_DAY` (30). demand: `FF_DEMAND_DAILY_CAP` (20 approvals per UTC day).
- trust: `FF_TRUST_REPORT_RATE_LIMIT` (5 per window), `FF_TRUST_VERIFICATION_RATE_LIMIT` (10 per window), `MAX_DOCS_PER_SUPPLIER` (30), `MAX_DOCS_PER_TYPE` (5), `MAX_TOTAL_DOCS` (20000).
