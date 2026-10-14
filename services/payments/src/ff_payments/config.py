from __future__ import annotations

from decimal import Decimal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ff_payments.dburl import resolve_auto_create


class Settings(BaseSettings):
    """Env prefix FF_PAYMENTS_. Secrets come from the environment only; none has a default."""

    model_config = SettingsConfigDict(env_prefix="FF_PAYMENTS_", env_file=".env", extra="ignore", env_ignore_empty=True)

    database_url: str = "sqlite+aiosqlite:///./payments.db"
    db_auto_create: bool | None = None  # None = auto: true for SQLite, false for PostgreSQL (use Alembic)

    @property
    def auto_create_tables(self) -> bool:
        return resolve_auto_create(self.database_url, self.db_auto_create)

    provider: str = "mock"  # mock | usdt_tron | off  (FF_PAYMENTS_PROVIDER)
    internal_token: str | None = None  # FF_INTERNAL_TOKEN is also honoured
    admin_token: SecretStr | None = None  # X-Admin-Token; admin endpoints are disabled when unset
    webhook_secret_mock: SecretStr | None = None
    webhook_secret_usdt_tron: SecretStr | None = None
    webhook_tolerance_seconds: int = 300

    invoice_ttl_minutes: int = 60
    rfq_url: str = "http://localhost:8105"
    deal_client: str = "http"  # http | mock

    outbox_max_attempts: int = 8  # then the event is dead-lettered (admin can requeue)
    outbox_backoff_seconds: int = 30  # doubles per attempt, capped at one hour
    outbox_lease_seconds: int = 60
    outbox_inline_timeout_seconds: float = 3.0  # best-effort immediate delivery after settlement

    commission_product: Decimal = Decimal("0.03")
    commission_raw_material: Decimal = Decimal("0.02")
    commission_production_line: Decimal = Decimal("0.04")
    min_commission_usd: Decimal = Decimal("25")

    # USDT-TRC20 (UNVERIFIED against a live chain). Public receiving address + explorer endpoint, env only.
    usdt_receive_address: str | None = None
    usdt_explorer_url: str | None = None  # e.g. a TronGrid-compatible base URL
    usdt_explorer_api_key: SecretStr | None = None
    usdt_contract: str | None = None  # TRC20 USDT contract address
    usdt_min_confirmations: int = 20

    def webhook_secret(self, provider: str) -> str | None:
        s = {"mock": self.webhook_secret_mock, "usdt_tron": self.webhook_secret_usdt_tron}.get(provider)
        return s.get_secret_value() if s else None
