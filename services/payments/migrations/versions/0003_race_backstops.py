"""Partial unique indexes closing races between workers.

* one live (pending/awaiting/confirming/paid) invoice per (deal, kind, payer)
* one on-chain transfer (provider, tx_ref) settles at most one invoice
* one outstanding (provider, pay_amount): the unique sub-cent suffix is the only thing identifying a USDT payer

Upgrade fails loudly if existing rows already violate them (resolve the duplicates by hand first).
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

LIVE = "status IN ('pending','awaiting_payment','confirming','paid')"
HOLDS_TX = "tx_ref IS NOT NULL AND status IN ('confirming','paid')"
HOLDS_AMT = "provider = 'usdt_tron' AND pay_amount IS NOT NULL AND status IN ('awaiting_payment','confirming')"


def upgrade() -> None:
    op.create_index("uq_invoices_live_deal_kind_payer", "invoices", ["deal_id", "kind", "payer_user_id"],
                    unique=True, sqlite_where=sa.text(LIVE), postgresql_where=sa.text(LIVE))
    op.create_index("uq_invoices_provider_tx_ref", "invoices", ["provider", "tx_ref"], unique=True,
                    sqlite_where=sa.text(HOLDS_TX), postgresql_where=sa.text(HOLDS_TX))
    op.create_index("uq_invoices_provider_pay_amount", "invoices", ["provider", "pay_amount"], unique=True,
                    sqlite_where=sa.text(HOLDS_AMT), postgresql_where=sa.text(HOLDS_AMT))


def downgrade() -> None:
    op.drop_index("uq_invoices_provider_pay_amount", table_name="invoices")
    op.drop_index("uq_invoices_provider_tx_ref", table_name="invoices")
    op.drop_index("uq_invoices_live_deal_kind_payer", table_name="invoices")
