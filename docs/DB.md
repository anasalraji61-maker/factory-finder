# Database migrations (Alembic)

Applies to the services with a database: **sourcing (native listings), rfq, messaging, tracking, notifications, demand, payments, media, feed, freight, trust**
(`gateway` has a small Alembic setup for its claim-decision tables). Each service owns its own Alembic
setup (`services/<svc>/alembic.ini` + `migrations/`) and its **own database**; there is no shared schema.

## URLs
`FF_<SVC>_DATABASE_URL`, e.g. `FF_RFQ_DATABASE_URL`. `postgresql://` and `postgres://` are rewritten
to `postgresql+asyncpg://` (sqlite -> `sqlite+aiosqlite://`). Install the driver with the `pg` extra:
`pip install -e "services/rfq[pg]"` (Docker: `FF_DOCKER_EXTRAS=pg`). Default stays a local SQLite file.

## Table creation flag
`FF_<SVC>_DB_AUTO_CREATE` (true/false). Unset = `true` for SQLite (dev, tests), `false` for PostgreSQL.
With PostgreSQL run migrations before starting the service.

## Workflow (run inside `services/<svc>`)
```
export FF_RFQ_DATABASE_URL=postgresql://ff:secret@localhost:5432/ff_rfq
alembic upgrade head                                  # apply
alembic revision --autogenerate -m "add column x"     # after changing the models; REVIEW the file
alembic downgrade -1                                  # roll back one revision
alembic upgrade head --sql > out.sql                  # offline SQL for DBAs
```
Rules: one linear history per service; never edit an applied revision (add a new one); write
reversible `downgrade()`; keep identifiers <= 63 chars (tests enforce it); render `sa.DateTime(timezone=True)`
rather than the service's own TypeDecorators in revision files; no network or secrets in revisions.

## Tests
`tests/test_migrations.py` in each service runs `alembic upgrade head` on a temp SQLite file, checks the tables
and `compare_metadata` (models vs migrated schema = no diff), and an upgrade/downgrade/upgrade round trip.

## Local PostgreSQL
```
export FF_POSTGRES_PASSWORD=...  FF_DOCKER_EXTRAS=pg
docker compose --profile pg up -d postgres
# create one database per service (ff_rfq, ff_messaging, ...) then point each FF_<SVC>_DATABASE_URL at postgres:5432
docker compose --profile pg run --rm rfq alembic upgrade head
```
Money notes: rfq stores money/quantities as exact decimal strings (never floats); notifications/demand/tracking keep
documents as JSON. A move to `Numeric(p, s)` columns would need a data-migrating revision.

## trust
`FF_TRUST_DATABASE_URL` / `FF_TRUST_DB_AUTO_CREATE`, default `sqlite+aiosqlite:///./data/trust.db`. Holds verification documents, the append-only
`verification_audit` (UPDATE/DELETE rejected by triggers; the migration installs them on SQLite and PostgreSQL), buyer reports,
score snapshots and `trust_meta`. Replaces the former loose DDL file. In `FF_ENV=production` the service also needs
`FF_TRUST_VERIFICATION_HASH_KEY` (stable secret; changing it breaks duplicate detection and is refused at startup).
Back up the database together with that key.

## Gateway account tables
`users` gained `deletion_scheduled_at` and `deleted_at`; new tables `deletion_jobs` (durable per-service erasure queue, unique per user and service) and `account_events` (audit). The gateway has Alembic (`services/gateway/alembic.ini`, revision `0001_claim_decisions`), but the account columns/tables above are still created/extended at startup (`create_tables` plus the lightweight migration in `ff_gateway/db`), not by an Alembic revision. Services need no schema change: erasure only updates or deletes existing rows.

## Latest revision per service (verified 2026-10-15 from `services/*/migrations/versions/`)
| Service | Latest revision |
|---|---|
| gateway | 0001_claim_decisions |
| sourcing | 0006_native_search_indexes |
| rfq | 0007_sweep_and_review_indexes |
| messaging | 0004_client_id_index |
| tracking | 0004_refresh_marker_and_list_indexes |
| notifications | 0004_list_indexes |
| demand | 0002_compliance |
| payments | 0003_race_backstops |
| media | 0003_owner_created_index |
| feed | 0001_initial |
| freight | 0002_one_pending_application |
| trust | 0004_reports_low_trust_index |
