"""Migrations: ``alembic upgrade head`` on a temp SQLite file matches the models; round-trips; guards survive."""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from ff_trust.db import metadata

SERVICE_DIR = Path(__file__).resolve().parent.parent
GUARDS = {"trg_verification_audit_no_update", "trg_verification_audit_no_delete"}


def _cfg(db: Path) -> Config:
    cfg = Config(str(SERVICE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db}")
    return cfg


def _engine(db: Path):
    return sa.create_engine(f"sqlite:///{db}")


def _tables(db: Path) -> set[str]:
    e = _engine(db)
    try:
        return set(sa.inspect(e).get_table_names()) - {"alembic_version"}
    finally:
        e.dispose()


def _triggers(db: Path) -> set[str]:
    e = _engine(db)
    try:
        with e.connect() as c:
            return {r[0] for r in c.execute(sa.text("select name from sqlite_master where type='trigger'"))}
    finally:
        e.dispose()


def test_single_linear_history():
    assert len(ScriptDirectory.from_config(_cfg(Path("x.db"))).get_heads()) == 1


def test_upgrade_matches_models(tmp_path):
    db = tmp_path / "mig.db"
    command.upgrade(_cfg(db), "head")
    assert _tables(db) == set(metadata.tables)
    e = _engine(db)
    try:
        with e.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), metadata)
    finally:
        e.dispose()
    assert diff == []


def test_postgres_identifier_limit():
    names = list(metadata.tables)
    for table in metadata.tables.values():
        names += [c.name for c in table.columns]
        names += [i.name for i in table.indexes if i.name]
        names += [c.name for c in table.constraints if c.name]
    assert [n for n in names if len(str(n)) > 63] == []


def test_downgrade_upgrade_round_trip(tmp_path):
    db = tmp_path / "mig.db"
    cfg = _cfg(db)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert _tables(db) == set() and _triggers(db) == set()
    command.upgrade(cfg, "head")
    assert _tables(db) == set(metadata.tables)


def test_migrated_schema_has_audit_guards_and_no_number_column(tmp_path):
    db = tmp_path / "mig.db"
    command.upgrade(_cfg(db), "head")
    assert _triggers(db) >= GUARDS
    e = _engine(db)
    try:
        cols = {c["name"] for c in sa.inspect(e).get_columns("verification_documents")}
        assert "number_masked" in cols and "number" not in cols
        with e.begin() as c:
            c.execute(sa.text("insert into verification_audit(at, actor, action, document_id, supplier_id) values ('2026-01-01','a','submit','d','s')"))
        with pytest.raises(sa.exc.DBAPIError, match="append-only"), e.begin() as c:
            c.execute(sa.text("delete from verification_audit"))
        with pytest.raises(sa.exc.IntegrityError), e.begin() as c:
            c.execute(sa.text("insert into verification_audit(at, actor, action, document_id, supplier_id) values ('2026-01-01','a','delete','d','s')"))
    finally:
        e.dispose()


def test_create_all_and_migration_agree_on_guards(tmp_path):
    """The dev auto-create path installs the same triggers as the migration."""
    e = _engine(tmp_path / "auto.db")
    try:
        metadata.create_all(e)
    finally:
        e.dispose()
    assert _triggers(tmp_path / "auto.db") >= GUARDS


def test_live_fingerprint_unique_index_is_partial(tmp_path):
    db = tmp_path / "mig.db"
    command.upgrade(_cfg(db), "head")
    ins = ("insert into verification_documents(id, supplier_id, doc_type, issuing_country, files, number_fingerprint, consent, status, created_at) "
           "values (:i, 's', 'business_license', 'CN', '[]', 'fp', 1, :st, '2026-01-01')")
    e = _engine(db)
    try:
        with e.begin() as c:
            c.execute(sa.text(ins), {"i": "a", "st": "withdrawn"})
            c.execute(sa.text(ins), {"i": "b", "st": "pending"})  # a closed duplicate does not block a live one
        with pytest.raises(sa.exc.IntegrityError), e.begin() as c:
            c.execute(sa.text(ins), {"i": "c", "st": "approved"})
    finally:
        e.dispose()
