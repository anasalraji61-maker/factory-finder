2026-10-14 | Alembic per service (rfq, messaging, tracking, notifications, demand), asyncpg for PostgreSQL via `pg` extra, `FF_<SVC>_DB_AUTO_CREATE` (default true for SQLite, false for PG) | stack decision: PostgreSQL + Alembic in prod, SQLite for dev/tests
2026-10-14 | rfq keeps money/quantity as exact decimal strings (not Numeric) | SQLite Numeric is lossy and the API/service code relies on exact strings; never Float
2026-10-14 | messaging index on conversation_participants given explicit short name | auto-generated name was 64 chars, over PostgreSQL's 63-byte limit
