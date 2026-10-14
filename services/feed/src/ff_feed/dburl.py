"""Database URL helpers shared by the app engine and Alembic (PostgreSQL via asyncpg)."""

from __future__ import annotations


def normalize_database_url(url: str) -> str:
    """Map sync-style URLs to async drivers.

    ``postgres://`` and ``postgresql://`` -> ``postgresql+asyncpg://``;
    ``sqlite://`` -> ``sqlite+aiosqlite://``. Explicit ``+driver`` URLs are left untouched.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    if url.startswith("sqlite://"):
        return "sqlite+aiosqlite://" + url.removeprefix("sqlite://")
    return url


def is_sqlite(url: str) -> bool:
    return normalize_database_url(url).startswith("sqlite")


def resolve_auto_create(url: str, flag: bool | None) -> bool:
    """``FF_<SVC>_DB_AUTO_CREATE``: explicit flag wins; default true for SQLite, false otherwise
    (PostgreSQL schemas are managed by Alembic migrations)."""
    return is_sqlite(url) if flag is None else flag
