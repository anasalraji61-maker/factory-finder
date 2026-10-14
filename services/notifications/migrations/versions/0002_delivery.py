"""delivery: notification_prefs + deliveries

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_prefs",
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("doc", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("owner_id"),
    )
    op.create_table(
        "deliveries",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("next_attempt_at", sa.String(length=32), nullable=False),
        sa.Column("doc", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("deliveries", schema=None) as batch_op:
        batch_op.create_index("ix_delivery_due", ["status", "next_attempt_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_deliveries_owner_id"), ["owner_id"], unique=False)


def downgrade() -> None:
    op.drop_table("deliveries")
    op.drop_table("notification_prefs")
