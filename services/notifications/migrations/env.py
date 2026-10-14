"""Alembic environment (async engine). URL precedence: ``-x``-less ``sqlalchemy.url`` option
(tests / programmatic use) > ``FF_NOTIFICATIONS_DATABASE_URL`` env > the service default."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from ff_notifications.config import Settings
from ff_notifications.dburl import normalize_database_url
from ff_notifications.persistence.store import metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = metadata


def _url() -> str:
    return normalize_database_url(config.get_main_option("sqlalchemy.url") or Settings().database_url)


def _configure(**kw) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=_url().startswith("sqlite"),
        **kw,
    )


def run_migrations_offline() -> None:
    _configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_do_run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
