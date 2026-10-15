"""claim_decisions: append-only audit of supplier-claim decisions

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "claim_decisions" in sa.inspect(op.get_bind()).get_table_names():  # already made by create_tables
        return
    op.create_table(
        "claim_decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=40), nullable=False),
        sa.Column("supplier_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("previous_status", sa.String(length=10), nullable=False),
        sa.Column("new_status", sa.String(length=10), nullable=False),
        sa.Column("reviewer", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claim_decisions_user_id", "claim_decisions", ["user_id"])
    op.create_index("ix_claim_decisions_supplier_id", "claim_decisions", ["supplier_id"])


def downgrade() -> None:
    op.drop_index("ix_claim_decisions_supplier_id", table_name="claim_decisions")
    op.drop_index("ix_claim_decisions_user_id", table_name="claim_decisions")
    op.drop_table("claim_decisions")
