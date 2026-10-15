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

---

## Re-verification (2026-10-15, later; PostgreSQL 16, throwaway cluster on port 5441, stopped and removed afterwards)
New/changed migrations covered: payments 0003, freight 0002, trust 0002, demand 0002, messaging 0003, sourcing 0005, rfq 0006 (plus notifications 0003, tracking 0003).
- **Alembic**: `upgrade head` from empty -> `downgrade base` -> `upgrade head` -> `alembic check` ("No new upgrade operations") OK for all 11 services; no migration defects found.
- **Suites on PG** (Mode A, `create_all`, harness plugin as before, now also forcing `db_auto_create` and running the schema reset in `pytest_runtest_setup`): payments, freight, rfq, trust, sourcing, messaging fully green;
  demand green except `tests/test_compliance_qa.py` (autouse `no_network` fixture blocks sockets, so the PG connection itself is refused: harness artefact, not a service defect).
- **Partial unique indexes on PG** (schema built by Alembic, 8 concurrent writers via asyncpg pool): payments `uq_invoices_live_deal_kind_payer`, `uq_invoices_provider_tx_ref`, `uq_invoices_provider_pay_amount`: exactly 1 insert wins, the rest raise `sqlalchemy.exc.IntegrityError` (sqlstate 23505, asyncpg `UniqueViolationError`); non-live (expired) duplicates still allowed.
  freight `uq_applications_one_pending` through `FreightService.apply`: 1 ok, the rest map to `Conflict` (`application_pending`) (the one remaining outcome was the per-user rate limiter, expected).
- Still unverified: unchanged from the list above (psycopg driver not installed; only asyncpg exercised).

---

## Re-verification 3 (2026-10-15; PostgreSQL 16, throwaway cluster on port 5452, stopped and removed afterwards)
New since the previous run: **gateway** (first Alembic setup, `0001_claim_decisions`), **trust 0003** (`released_at`), media 0002 (`visibility`) checked too. Full migration list diffed against this doc: no other new revisions.
- **Alembic, 11 services + gateway**: `upgrade head` (empty) -> `downgrade base` -> `upgrade head` -> `alembic check` all OK, including trust 0003 and media 0002; no migration defects.
- **Gateway by design only migrates `claim_decisions`**; every other table (users, tokens, deletion_jobs, account_events) still comes from `create_tables` (`create_all` + `_add_missing_columns`) in the app lifespan. So `alembic check` on a DB built *only* by migrations reports the other 5 tables as missing: expected, not a defect, but a production PG DB must still start the app once (or run `create_tables`) before it is complete.
  Both orders verified on PG: (A) `create_tables` twice then `alembic upgrade head` (guard skips existing `claim_decisions`, version stamped 0001, `alembic check` clean); (B) `alembic upgrade head` then `create_tables` (no error, `alembic check` clean, 8 tables). Lifespan startup on PG exercised by the whole gateway suite.
- **Suites on PG** (same harness idea, Mode A `create_all`): gateway fully green (all tests). trust green except 3 harness artefacts (`test_default_settings_and_url_handling`, `test_default_file_database_is_created_in_data_dir` assert SQLite defaults; `test_rate_limit_and_caps` shares one DB). trust Mode B (schema via `alembic upgrade head`, auto-create off): same 3 only.
- Fixed: gateway `alembic.ini` comment named `FF_MESSAGING_DATABASE_URL` (actual var is `FF_GATEWAY_DATABASE_URL`).
- Still unverified: unchanged (pool behaviour, psycopg driver, docker `pg` profile, production TLS URL options).
