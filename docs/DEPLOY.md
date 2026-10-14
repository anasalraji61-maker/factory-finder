# Deploy / docker compose

## Verification status (honest)
- VERIFIED: `docker compose config -q` passes; env var names in `docker-compose.yml` were cross-checked against each service's `config.py` (prefixes `FF_<SERVICE>_`, `FF_INTERNAL_TOKEN`); Dockerfile and healthcheck commands read statically (`python` + `urllib` exist in `python:3.12-slim`); `scripts/e2e.py` parses.
- NOT VERIFIED: **no real `docker compose up --build` run has succeeded.** In the CI sandbox the daemon could be started, but Docker Hub (`registry-1.docker.io`) returns 403, so `python:3.12-slim` cannot be pulled and no image was built. Image builds, container startup, healthchecks and the compose e2e are untested. Run `make compose-e2e` on a machine with Docker Hub access.

## Run
```
cp .env.example .env        # fill secrets (see below)
docker compose up --build   # gateway on :8000, all other services internal only
FF_E2E_BASE_URL=http://localhost:8000 python scripts/e2e.py   # smoke test against the stack
make compose-e2e            # up -d --wait, e2e, down -v
docker compose down -v
```
`FF_E2E_BASE_URL` makes `scripts/e2e.py` skip spawning local processes and the two steps that need unpublished service ports. Default behaviour is unchanged. The gateway has `/health` (no `/ready`).

## Production-ish checklist
- Secrets only via env / `.env` (never committed; the repo is public). Generate: `python -c 'import secrets;print(secrets.token_urlsafe(48))'`.
- Set `FF_GATEWAY_JWT_SECRET` (otherwise an ephemeral secret is generated and tokens die on restart) and `FF_INTERNAL_TOKEN` (shared gateway->service token).
- Admin: `FF_GATEWAY_ADMIN_TOKEN` enables `/v1/admin/*` (unset = 404). Use a long random value; keep it off client apps.
- CORS: `FF_GATEWAY_CORS_ORIGINS` is a JSON list, default `[]` (native app needs none). List exact web origins only; never `*`.
- Only the gateway publishes a port. Put a reverse proxy (Caddy/nginx/Traefik) in front for TLS, bind the gateway to `127.0.0.1:8000`, and do not publish backend ports.
- PostgreSQL: `FF_DOCKER_EXTRAS=pg`, `FF_POSTGRES_PASSWORD=...`, one DB per service (`FF_RFQ_DATABASE_URL=postgresql://ff:<pw>@postgres:5432/ff_rfq`, same for messaging/tracking/notifications/demand), `docker compose --profile pg up --build`, create the databases, then `docker compose run --rm <svc> alembic upgrade head` (see `docs/DB.md`). Auto-create is off for Postgres.
- Default SQLite files live inside containers and are lost on recreate: use Postgres for anything real. The gateway's own DB (users) is SQLite by default (`FF_GATEWAY_DATABASE_URL`), mount a volume or move it to Postgres before real use.
- Backups: `pg_dump` per database on a schedule, store off-host, test restores; back up the `pgdata` volume only as a secondary measure.
- Real provider adapters are OFF by default and unverified against live APIs; keep kill switches (`FF_*_KILL_SWITCH`) documented for operators. Demand matching stays disabled (`FF_DEMAND_ENABLED=false`) unless a human-in-the-loop is in place.
- Pin base image digests and dependency versions for reproducible builds; run containers as non-root (already done: user `app`).

## Env forwarding and feed admin
`docker-compose.yml` forwards the operator switches (`FF_ENV`, kill switches, gateway mail/admin-UI, sourcing/logistics/tracking/notifications provider vars, assistant LLM, admin tokens) with empty or code-default fallbacks; unset means unchanged behaviour. Full list and exceptions: `docs/RUNBOOK.md` (top). `/v1/admin/feed/*` (`FF_FEED_ADMIN_TOKEN`) is not routed by the gateway; moderate from the private network only. Same for `/v1/admin/freight/*` (`FF_FREIGHT_ADMIN_TOKEN`): forwarder application approval and freight moderation are service-local.

## Public ingress for payments webhooks
`POST /v1/payments/webhooks/{provider}` is called by external payment providers, which cannot send a user bearer token, so the gateway
(which requires auth for `/v1/payments/*`) cannot serve it. Open question for the operator before enabling real providers: expose the
payments service webhook path only, through a dedicated public ingress that bypasses the gateway. Requirements:
- Route ONLY `POST /v1/payments/webhooks/*` to the payments service from the reverse proxy; never expose any other payments path or port.
- Authenticity rests on the HMAC `X-FF-Signature` (`FF_PAYMENTS_WEBHOOK_SECRET_*`, 300 s tolerance, replay protection); keep secrets set, otherwise webhooks answer 503.
- Apply proxy-level rate limiting and a small body-size cap; optionally allow-list the provider's source IPs.
- Webhooks skip the internal-token check by design, so do not route other traffic to payments through this ingress.
Decision pending: no gateway change is made for this.

## Moderation admin token
Gateway-side `FF_SOURCING_ADMIN_TOKEN` (sourcing's service admin token) is injected by the gateway for `/v1/admin/moderation/*`; callers only
present `X-Admin-Token` (= `FF_GATEWAY_ADMIN_TOKEN`). Unset = those routes answer 404.
