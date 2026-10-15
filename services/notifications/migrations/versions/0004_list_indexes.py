"""additive composite indexes for inbox listing, retention prune and per-owner delivery/watch listing

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_IDX = [
    ("ix_watch_owner_id", "watches", ["owner_id", "id"]),
    ("ix_alert_owner_created", "alerts", ["owner_id", "created_at", "id"]),
    ("ix_alert_owner_read", "alerts", ["owner_id", "read"]),
    ("ix_alert_created", "alerts", ["created_at"]),
    ("ix_delivery_owner_id", "deliveries", ["owner_id", "id"]),
]


def upgrade() -> None:
    for name, table, cols in _IDX:
        op.create_index(name, table, cols)


def downgrade() -> None:
    for name, table, _ in reversed(_IDX):
        op.drop_index(name, table_name=table)
