# PostgreSQL verification (2026-10-15)

## Setup
No Docker, but the sandbox has PostgreSQL 16 binaries (`/usr/lib/postgresql/16/bin`). Ran `initdb` + `pg_ctl` as the `postgres` OS user
on port 5433 (socket `/tmp`, data `/tmp/pgdata`, trust auth, local only), one database per service (`ff_<svc>`, 12 total).
Driver: `asyncpg` 0.32 installed into the repo `.venv` (needed for `postgresql+asyncpg://`; already declared by the `pg` extra).
The server was stopped afterwards.

## What was run
1. `alembic upgrade head` for all 11 Alembic services (demand, feed, freight, media, messaging, notifications, payments, rfq, sourcing, tracking, trust):
   all OK. Then `downgrade base` -> `upgrade head` round trip: OK. `alembic check` (models vs migrated schema): "No new upgrade operations" for all 11.
2. Every service's existing pytest suite re-run against PostgreSQL (rfq, trust, feed, freight, payments, messaging, notifications, tracking,
   sourcing, media, demand, gateway). Harness (not committed, in the session scratchpad): a pytest plugin that rewrites in-memory SQLite
   `database_url` Settings to the service's PG database, drops/recreates schema per test, uses NullPool (tests mix event loops).
   Services then take their real PostgreSQL code paths (`is_sqlite` false: FOR UPDATE, `pg_advisory_xact_lock`, JSONB, tz columns, audit triggers).
   - Mode A (tables via `create_all`): all services green except harness artefacts below.
   - Mode B (schema built by `alembic upgrade head`, `db_auto_create=false`): rfq, trust, feed, freight, payments, messaging, notifications,
     tracking, sourcing, media, demand green (same exception).
   - gateway: Mode A only (it has no Alembic; `create_tables` + lightweight column migration ran fine on PG).

## Found and fixed
- **notifications `mark_alerts_read` (PG branch)**: `cast(patch_str, JSONB)` bound the Python string through the JSONB bind processor, so
  the patch became a JSON *string scalar*; `doc || scalar` yields a JSON array and the next read crashed (`list indices must be integers`).
  Fixed in `services/notifications/src/ff_notifications/persistence/store.py` by binding the patch as `literal(patch, String)` before the JSONB cast.
  SQLite path untouched; sqlite suite green; ruff clean.

## Not a bug (harness artefacts)
- trust `test_rate_limit_and_caps` builds two apps in one test; with one shared PG database they share state (sqlite `:memory:` gave each its own DB).

## Still unverified
- Real concurrency under load (two replicas racing on `FOR UPDATE` / advisory locks): only the in-suite concurrency tests ran, single process.
- Pooled connections (`AsyncAdaptedQueuePool`, `pool_pre_ping`) were replaced by NullPool in the harness; pool behaviour across loops/reconnects untested.
- Gateway migrations (none exist), docker-compose `pg` profile, and `FF_DOCKER_EXTRAS=pg` image build.
- Data-migrating changes (e.g. a future move of rfq money strings to `Numeric`), large-volume index/query plans, and `pg_dump` restore.
- Production-mode settings (`FF_ENV=production`, TLS `sslmode`, asyncpg URL query options such as `?sslmode=` which asyncpg does not accept as-is).
