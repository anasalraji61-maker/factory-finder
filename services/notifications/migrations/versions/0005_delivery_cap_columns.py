"""deliveries: indexed channel/device_id/created_at columns (backfilled from doc) for the push cap COUNT

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("deliveries") as b:
        b.add_column(sa.Column("channel", sa.String(length=16), nullable=True))
        b.add_column(sa.Column("device_id", sa.String(length=64), nullable=True))
        b.add_column(sa.Column("created_at", sa.String(length=32), nullable=True))
    t = sa.table(
        "deliveries",
        sa.column("id", sa.String),
        sa.column("doc", sa.JSON),
        sa.column("channel", sa.String),
        sa.column("device_id", sa.String),
        sa.column("created_at", sa.String),
    )
    conn = op.get_bind()
    for row in conn.execute(sa.select(t.c.id, t.c.doc)).all():
        doc = row.doc
        if isinstance(doc, str):
            import json

            doc = json.loads(doc)
        conn.execute(
            sa.update(t)
            .where(t.c.id == row.id)
            .values(
                channel=doc.get("channel"),
                device_id=doc.get("device_id"),
                created_at=doc.get("created_at"),
            )
        )
    op.create_index(
        "ix_delivery_cap", "deliveries", ["owner_id", "channel", "device_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_cap", table_name="deliveries")
    with op.batch_alter_table("deliveries") as b:
        b.drop_column("created_at")
        b.drop_column("device_id")
        b.drop_column("channel")
