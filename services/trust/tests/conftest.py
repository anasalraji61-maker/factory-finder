import contextlib

import pytest


@pytest.fixture(autouse=True)
def _isolated_database(monkeypatch):
    """Every create_app() gets its own private in-memory SQLite database (no files, no cross-test state)."""
    monkeypatch.setenv("FF_TRUST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.delenv("FF_ENV", raising=False)
    monkeypatch.delenv("FF_TRUST_VERIFICATION_HASH_KEY", raising=False)


@pytest.fixture(autouse=True)
def _dispose_databases(monkeypatch):
    """Close every engine a test created (in-memory SQLite keeps a worker thread per connection)."""
    import asyncio

    from ff_trust import db as dbmod

    made: list = []
    orig = dbmod.Database.__init__

    def tracking(self, *a, **kw):
        orig(self, *a, **kw)
        made.append(self)

    monkeypatch.setattr(dbmod.Database, "__init__", tracking)
    yield
    for d in made:
        with contextlib.suppress(Exception):
            asyncio.run(d.dispose())
