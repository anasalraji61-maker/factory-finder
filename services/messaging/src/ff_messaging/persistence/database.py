"""Async engine wrapper with explicit read / write transaction scopes."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager, nullcontext
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from ff_messaging.persistence.tables import metadata


def normalize_database_url(url: str) -> str:
    """Map sync-style URLs to their async drivers (``postgresql://`` -> ``postgresql+psycopg://``)."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    if url.startswith("sqlite://"):
        return "sqlite+aiosqlite://" + url.removeprefix("sqlite://")
    return url


def _configure_sqlite(engine: AsyncEngine) -> None:
    """SQLite: foreign keys on, and ``BEGIN IMMEDIATE`` so writers queue instead of failing.

    pysqlite's implicit transaction handling is disabled (``isolation_level = None``) and the
    transaction is started explicitly, per the SQLAlchemy recipe for (aio)sqlite.
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    @event.listens_for(engine.sync_engine, "begin")
    def _on_begin(connection: Connection) -> None:
        connection.exec_driver_sql("BEGIN IMMEDIATE")


class Database:
    """Owns the engine. SQLite access is serialised in-process (single writer by design;
    in-memory test databases share one connection); PostgreSQL relies on row locks."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = normalize_database_url(url)
        backend = make_url(self.url).get_backend_name()
        self.is_sqlite = backend == "sqlite"
        kwargs: dict[str, Any] = {"echo": echo}
        if not self.is_sqlite:
            kwargs["pool_pre_ping"] = True
        self.engine: AsyncEngine = create_async_engine(self.url, **kwargs)
        self._lock: asyncio.Lock | None = None
        if self.is_sqlite:
            _configure_sqlite(self.engine)
            self._lock = asyncio.Lock()

    def _guard(self) -> AbstractAsyncContextManager[Any]:
        return self._lock if self._lock is not None else nullcontext()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        """Read-write transaction: committed on success, rolled back on any exception."""
        async with self._guard(), self.engine.begin() as connection:
            yield connection

    @asynccontextmanager
    async def read(self) -> AsyncIterator[AsyncConnection]:
        """Read-only scope (rolled back on exit)."""
        async with self._guard(), self.engine.connect() as connection:
            yield connection

    async def create_all(self) -> None:
        async with self.transaction() as connection:
            await connection.run_sync(metadata.create_all)

    async def ping(self) -> bool:
        from sqlalchemy import text

        async with self.read() as connection:
            await connection.execute(text("SELECT 1"))
        return True

    async def dispose(self) -> None:
        await self.engine.dispose()
