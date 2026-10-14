# Runbook (incidents)

Audience: whoever operates the stack (docker compose). Env names below were verified against the service `config.py` files and adapters. Companion docs: `docs/DEPLOY.md`, `docs/OPS.md`, `docs/DB.md`, `docs/API_OVERVIEW.md`.

Important compose caveat: `docker-compose.yml` passes only the env vars listed in its `environment:` blocks into containers (e.g. gateway: `FF_GATEWAY_JWT_SECRET`, `FF_INTERNAL_TOKEN`, `FF_GATEWAY_CORS_ORIGINS`, `FF_GATEWAY_ADMIN_TOKEN`). Many switches below (kill switches, `FF_ENV`, `FF_GATEWAY_SERVE_ADMIN`, `FF_NOTIFY_*`, `FF_TRACKING_*`, `FF_LOGISTICS_FREIGHT_*`, `FF_SOURCING_ADAPTERS`, `FF_PAYMENTS_ADMIN_TOKEN` on the gateway ...) are NOT forwarded yet: adding them to a `.env` file alone has no effect until the matching line is added to `docker-compose.yml` (or a `docker-compose.override.yml`) under that service's `environment:`. Check with `docker compose config | grep <NAME>`.

## 1. Quick triage

```
docker compose ps                                  # which container is unhealthy/restarting
docker compose logs --tail=200 <service>           # JSON lines; find "status":5xx and request_id
curl -s localhost:8000/health ; curl -s localhost:8000/ready   # /ready lists upstreams {name: bool}; "degraded" = a backend is down
```
Probes: `GET /health` (liveness) and `GET /ready` (DB reachable) exist on every service (internal ports 8101-8112, reach them with `docker compose exec <svc> python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:<port>/ready').read())"`). Correlate by `request_id` (gateway forwards `X-Request-Id`). Set `FF_LOG_FORMAT=text` for readable local logs.

## 2. A service is down

1. `docker compose ps` / `docker compose logs --tail=200 <svc>`.
2. Startup refusal with `RuntimeError: FF_ENV=production requires ...`: the production guard is on and a token is missing. rfq, payments, notifications, sourcing, tracking, messaging, media need `FF_INTERNAL_TOKEN`; the gateway needs `FF_GATEWAY_JWT_SECRET` and `FF_GATEWAY_ADMIN_TOKEN`. Fix the env, then restart.
3. `docker compose restart <svc>`; if the image is stale: `docker compose up -d --build <svc>`.
4. Effects of each service being down (the gateway keeps running; `/ready` shows `degraded`): sourcing -> search/listings fail (assistant and notifications depend on it); logistics -> quotes fail; geo -> logistics cannot resolve places; trust -> sourcing falls back (trust mode `http` has a 0.8 s timeout); rfq -> requests/offers/deals; payments -> invoices (settlement events wait in the payments outbox and retry); tracking -> shipments (tracking outbox to notifications retries with backoff, then marks rows dead after `FF_TRACKING_NOTIFY_MAX_ATTEMPTS` = 8); media -> image uploads/reads.
5. Gateway down: nothing is reachable to clients. Check its DB (`FF_GATEWAY_DATABASE_URL`, SQLite by default; `/ready` is 503 only when the gateway DB is down) and that `FF_GATEWAY_UPSTREAMS` JSON is valid.
6. Dead payment events: admin console "Payments outbox" tab, or `GET /v1/admin/payments/outbox?status=dead` and `POST /v1/admin/payments/outbox/{id}/requeue` (header `X-Admin-Token`; needs `FF_PAYMENTS_ADMIN_TOKEN` set on the gateway too, same value as on payments, otherwise 404).

## 3. Database restore

Databases: one per service. gateway (users, default SQLite), sourcing (native listings), rfq, messaging, tracking, notifications, demand, payments, media (metadata; image files live on the `media-data` volume). trust, logistics, geo, assistant are stateless.

Backup (Postgres profile `pg`, user `ff`):
```
docker compose exec postgres pg_dump -U ff -Fc ff_rfq > backup/ff_rfq-$(date +%F).dump     # repeat per database
docker run --rm -v <project>_media-data:/d -v $PWD/backup:/b alpine tar czf /b/media-$(date +%F).tgz -C /d .
```
Restore (one database):
```
docker compose stop gateway <svc>
docker compose exec -T postgres psql -U ff -c "DROP DATABASE IF EXISTS ff_rfq" -c "CREATE DATABASE ff_rfq"
docker compose exec -T postgres pg_restore -U ff -d ff_rfq --no-owner < backup/ff_rfq-YYYY-MM-DD.dump
docker compose run --rm <svc> alembic upgrade head     # bring the schema to the current revision
docker compose up -d <svc> gateway
```
SQLite default (dev only): the DB file is inside the container (`/app/...`) and is lost on recreate; copy it out with `docker compose cp <svc>:/app/<file>.db backup/` before any rebuild. Move the gateway DB (`FF_GATEWAY_DATABASE_URL`) and the others to Postgres or a mounted volume before real users. After any restore, test: login, open a request, `GET /ready`. Never edit applied Alembic revisions (see `docs/DB.md`). Nothing in the repo verifies a restore for you: do a trial restore on a spare machine before launch.

## 4. Token and secret rotation

All values live only in the environment / `.env` (never in git; the repo is public). Generate: `python -c 'import secrets;print(secrets.token_urlsafe(48))'`. After changing, recreate the affected containers: `docker compose up -d <svc>`.

| Secret | Env | Effect of rotating |
|---|---|---|
| User JWT signing key | `FF_GATEWAY_JWT_SECRET` | All access and refresh tokens become invalid; every user must log in again. If unset, an ephemeral key is generated and tokens die on every restart. |
| Admin token | `FF_GATEWAY_ADMIN_TOKEN` | Admin console and `/v1/admin/*` need the new value; unset = those routes answer 404. If leaked: rotate at once, then review supplier-claim approvals and demand drafts. |
| Internal service token | `FF_INTERNAL_TOKEN` | Must be identical on the gateway and every service; rotate them all in one `docker compose up -d`. During a partial rollout calls fail with 401 `invalid_internal_token`. |
| Payments admin token | `FF_PAYMENTS_ADMIN_TOKEN` | Set the same value on payments and on the gateway. |
| Payments webhook secrets | `FF_PAYMENTS_WEBHOOK_SECRET_MOCK`, `FF_PAYMENTS_WEBHOOK_SECRET_USDT_TRON` | Update the sender (HMAC `X-FF-Signature`, 300 s tolerance) at the same time; unset = webhooks answer 503. |
| Sourcing moderation admin token | `FF_SOURCING_ADMIN_TOKEN` | Set on sourcing and (same value) on the gateway; unset = `/v1/admin/moderation/*` answers 404. |
| Provider keys | `FF_SOURCING_ALIBABA_APP_KEY`, `FF_SOURCING_ALIBABA_APP_SECRET`, `FF_SOURCING_ALIBABA_ACCESS_TOKEN`, `FF_LOGISTICS_FREIGHT_API_KEY`, `FF_TRACKING_CONTAINER_API_KEY`, `FF_TRACKING_AWB_API_KEY`, `FF_TRACKING_VESSEL_API_KEY`, `FF_NOTIFY_SMTP_PASSWORD`, `FF_GATEWAY_SMTP_PASSWORD`, `FF_NOTIFY_FCM_CREDENTIALS_JSON`/`_FILE`, `FF_MEDIA_S3_ACCESS_KEY_ID`/`_SECRET_ACCESS_KEY`, `FF_ASSISTANT_LLM_API_KEY`, `FF_PAYMENTS_USDT_EXPLORER_API_KEY` | Revoke at the provider first if leaked, create a new one, update env, restart the one service. |
| Postgres password | `FF_POSTGRES_PASSWORD` + each `FF_<SVC>_DATABASE_URL` | `ALTER USER ff PASSWORD '...'` inside Postgres, then update every URL and restart the services. |

If any secret was ever committed or pasted publicly: treat it as leaked and rotate it; removing it from git history is not enough.
Per-user: disabling a user (`is_active`) takes effect on the next proxied request after at most ~5 s. `POST /v1/auth/logout` revokes a refresh-token family; replaying a used refresh token revokes the whole family.

## 5. Kill switches (exact names found in code)

Truthy values for the `*_KILL_SWITCH` / `*_DISABLED` flags: the code accepts `1`, `true`, `yes`, `on` (case-insensitive); use `1`. They are read at call time from the process environment, so setting them needs the env var in the container (see the compose caveat at the top) and normally a container recreate.

| Goal | Switch | Service | Behaviour |
|---|---|---|---|
| Stop all real supplier-data adapters | `FF_SOURCING_KILL_SWITCH=1` | sourcing | Real adapters disabled; mock/native results continue, `sources[].warning` is set. |
| Stop only the Alibaba Open Platform adapter | `FF_SOURCING_ALIBABA_OPENAPI_DISABLED=1` | sourcing | Same, one adapter. |
| Turn real adapters off by config | unset/empty `FF_SOURCING_ADAPTERS` (default) and keep `FF_SOURCING_ENABLED_SOURCES=mock,native` | sourcing | Only mock + native listings are queried. |
| Stop all live freight rates | `FF_LOGISTICS_KILL_SWITCH=1` | logistics | Built-in tables are used. |
| Stop only the HTTP freight provider | `FF_LOGISTICS_FREIGHT_DISABLED=1` (or `FF_LOGISTICS_FREIGHT_PROVIDER=mock`) | logistics | Built-in tables. |
| Live FX off | `FF_LOGISTICS_FX_PROVIDER=mock` (values: `mock`, `ecb`) | logistics | Deterministic mock rates. |
| Stop all real tracking providers | `FF_TRACKING_KILL_SWITCH=1` | tracking | Responses carry a `warning` (e.g. `provider_unavailable:kill_switch`); mock fallback when `FF_TRACKING_FALLBACK_TO_MOCK` is true (default). |
| Per tracking provider | `FF_TRACKING_CONTAINER_DISABLED=1`, `FF_TRACKING_AWB_DISABLED=1`, `FF_TRACKING_VESSEL_DISABLED=1`, `FF_TRACKING_HTTP_DISABLED=1` | tracking | One provider off. Also `FF_TRACKING_PROVIDER=mock` (default). |
| Stop background tracking refresh | `FF_TRACKING_REFRESH_JOB_ENABLED=false` (default) | tracking | No scheduled provider calls. |
| Stop tracking -> notifications relay | `FF_TRACKING_NOTIFY_RELAY=off` (default; `on` enables) | tracking | Shipment alerts not forwarded. |
| Stop push notifications | `FF_NOTIFY_PUSH=off` (values: `off`, `mock`, `fcm`) | notifications | No device pushes. |
| Stop email digests | `FF_NOTIFY_EMAIL=off` (values: `off`, `mock`, `smtp`) | notifications | No digest mail. |
| Stop scheduled alert evaluation | `FF_NOTIFICATIONS_SCHEDULER_ENABLED=false` (default) | notifications | Alerts evaluated only when triggered internally. |
| Stop verification/other gateway mail | `FF_GATEWAY_MAIL_BACKEND=off` (values: `off`, `mock`, `smtp`) | gateway | No mail; if `FF_GATEWAY_REQUIRE_EMAIL_VERIFIED=true` is on, users who are not verified stay blocked from payments/claims/listings, so switch that off too. |
| Stop all payments | `FF_PAYMENTS_PROVIDER=off` (values: `mock`, `usdt_tron`, `off`) | payments | Invoice creation returns 503. Webhooks need their secrets, unset = 503. |
| Demand matching (public-reply drafting) | `FF_DEMAND_ENABLED=false` (default) | demand | Global kill switch: `approve` and `mark-published` return 403. Daily approvals capped by `FF_DEMAND_DAILY_CAP` (default 20). Keep OFF without a human reviewer. |
| Assistant LLM | `FF_ASSISTANT_LLM=off` (values: `off`, `mock`, `anthropic`); `FF_ASSISTANT_LLM_REWRITE=false` | assistant | Rule-based parsing only; no external LLM calls. Per-day quotas: `FF_ASSISTANT_QUOTA_PER_DAY` (200), `FF_ASSISTANT_ANON_QUOTA_PER_DAY` (30). |
| Admin console / admin API off | unset `FF_GATEWAY_ADMIN_TOKEN` (routes answer 404); `FF_GATEWAY_SERVE_ADMIN=false` (default) hides the `/admin/` static console | gateway | |
| Chat abuse filter | `FF_MESSAGING_ABUSE_FILTER_ENABLED` (default true), action `FF_MESSAGING_ABUSE_ACTION` | messaging | Flags/blocks messages matching the term list. |
| Hide one bad listing | admin console Moderation tab, or `POST /v1/admin/moderation/listings/{id}/hide` | sourcing via gateway | Reversible with `.../restore`. |
| Block a user | set `is_active` false on the user (effect within ~5 s) | gateway | No self-service endpoint; do it in the gateway DB. |

Production guard (not a kill switch, but a safety net): `FF_ENV=production` makes services refuse to start without their tokens (section 2).

## 6. Common incidents

- **Users suddenly logged out everywhere**: gateway restarted without `FF_GATEWAY_JWT_SECRET` (ephemeral key) or the secret was rotated. Set a fixed secret.
- **429 Too Many Requests for many users**: behind a proxy without `FF_GATEWAY_TRUSTED_PROXIES`, all clients share one IP. Set it to the proxy CIDRs. Limits: `FF_GATEWAY_RATE_LIMIT_PER_MINUTE` (300), `FF_GATEWAY_AUTH_RATE_LIMIT_PER_MINUTE` (30), `FF_GATEWAY_USER_WRITE_RATE_LIMIT_PER_MINUTE` (120), `FF_GATEWAY_MEDIA_RATE_LIMIT_PER_MINUTE` (3000). Multiple replicas need `FF_GATEWAY_REDIS_URL`.
- **Search returns only demo data**: expected. Real adapters are off until `FF_SOURCING_ADAPTERS` lists one and credentials are set (and they are unverified against live APIs).
- **Prices look stale/odd**: freight/duty tables are approximations unless a freight provider is configured; FX is mock unless `FF_LOGISTICS_FX_PROVIDER=ecb`.
- **Images missing after redeploy**: the `media-data` volume was not mounted/persisted or `FF_MEDIA_PUBLIC_BASE_URL` points to the wrong origin.
- **Suspected admin-token guessing**: the gateway throttles failed `/v1/admin` attempts per IP; rotate `FF_GATEWAY_ADMIN_TOKEN` anyway and check logs for 401s on `/v1/admin`.
- **Payment received but deal not marked paid**: look at the payments outbox for `pending`/`dead` events and requeue (section 2, step 6); check `docker compose logs rfq`.
- **Security finding follow-up**: open items are tracked in `docs/fixes/*.md` (blocks a phase until fixed).
