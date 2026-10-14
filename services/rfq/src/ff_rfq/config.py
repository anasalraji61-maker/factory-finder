from __future__ import annotations

from decimal import Decimal

from pydantic_settings import BaseSettings, SettingsConfigDict

from ff_rfq.dburl import resolve_auto_create


class Settings(BaseSettings):
    """Env prefix FF_RFQ_."""

    model_config = SettingsConfigDict(env_prefix="FF_RFQ_", env_file=".env", extra="ignore", env_ignore_empty=True)

    database_url: str = "sqlite+aiosqlite:///./rfq.db"
    # Create tables at startup (dev). None = auto: true for SQLite, false for PostgreSQL
    # (production schemas come from Alembic migrations: ``alembic upgrade head``).
    db_auto_create: bool | None = None

    @property
    def auto_create_tables(self) -> bool:
        return resolve_auto_create(self.database_url, self.db_auto_create)
    sourcing_url: str = "http://localhost:8101"
    sourcing_client: str = "http"  # http | mock
    commission_product: Decimal = Decimal("0.03")
    commission_raw_material: Decimal = Decimal("0.02")
    commission_production_line: Decimal = Decimal("0.04")
    min_commission_usd: Decimal = Decimal("25")
    # True: a deal is only `paid` once BOTH commission and deal_payment are paid, even if payments has not
    # yet reported the second invoice (closes the 'pay supplier, skip commission' gap). Default: the rule in deals.py.
    require_both_invoices: bool = False
    internal_token: str | None = None  # FF_INTERNAL_TOKEN is also honoured
