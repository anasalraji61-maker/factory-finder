# Database migrations (Alembic)

Applies to the services with a database: **sourcing (native listings), rfq, messaging, tracking, notifications, demand, payments**
(`trust` is stateless; `gateway` is handled separately). Each service owns its own Alembic
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
