"""Migrations: ``alembic upgrade head`` on a temp SQLite file matches the models; round-trips."""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from ff_notifications.persistence.store import metadata

SERVICE_DIR = Path(__file__).resolve().parent.parent
METADATA = metadata


def _cfg(db: Path) -> Config:
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db}")
    return cfg


def _tables(db: Path) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        return set(sa.inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_upgrade_matches_models(tmp_path):
    db = tmp_path / "mig.db"
    command.upgrade(_cfg(db), "head")
    assert _tables(db) == set(METADATA.tables)
    engine = sa.create_engine(f"sqlite:///{db}")
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": True})
            diff = compare_metadata(ctx, METADATA)
    finally:
        engine.dispose()
    assert diff == []


def test_postgres_identifier_limit():
    """PostgreSQL truncates / rejects identifiers over 63 bytes."""
    names = list(METADATA.tables)
    for table in METADATA.tables.values():
        names += [c.name for c in table.columns]
        names += [i.name for i in table.indexes if i.name]
        names += [c.name for c in table.constraints if c.name]
    assert [n for n in names if len(str(n)) > 63] == []


def test_downgrade_upgrade_round_trip(tmp_path):
    db = tmp_path / "mig.db"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert _tables(db) == set()
    command.upgrade(cfg, "head")
    assert _tables(db) == set(METADATA.tables)


def test_url_normalisation_and_auto_create_flag():
    from ff_notifications.config import Settings
    from ff_notifications.dburl import normalize_database_url

    assert normalize_database_url("postgresql://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert normalize_database_url("postgres://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"
    assert normalize_database_url("sqlite:///x.db") == "sqlite+aiosqlite:///x.db"
    assert Settings(database_url="sqlite+aiosqlite:///x.db").auto_create_tables is True
    assert Settings(database_url="postgresql://u:p@h/db").auto_create_tables is False
    forced = Settings(database_url="postgresql://u:p@h/db", db_auto_create=True)
    assert forced.auto_create_tables is True


def test_0003_creates_verification_table_and_downgrades(tmp_path):
    db = tmp_path / "mig.db"
    cfg = _cfg(db)
    command.upgrade(cfg, "0002")
    assert "email_verifications" not in _tables(db)
    command.upgrade(cfg, "0003")
    assert "email_verifications" in _tables(db)
    command.downgrade(cfg, "0002")
    assert "email_verifications" not in _tables(db) and "notification_prefs" in _tables(db)
