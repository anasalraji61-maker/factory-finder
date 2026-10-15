"""refresh_marker column (backfilled) + shipment list / refresh-due indexes

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15 12:00:00
"""
import json

import sqlalchemy as sa
from alembic import op


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('shipments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('refresh_marker', sa.DateTime(timezone=True), nullable=True))
    conn = op.get_bind()
    shipments = sa.table('shipments', sa.column('id', sa.String), sa.column('data', sa.Text),
                         sa.column('status', sa.String), sa.column('refresh_marker', sa.DateTime(timezone=True)))
    from datetime import UTC, datetime
    never, delivered = datetime(1970, 1, 1, tzinfo=UTC), datetime(9999, 12, 31, tzinfo=UTC)
    conn.execute(shipments.update().where(shipments.c.status == 'delivered').values(refresh_marker=delivered))
    last_id = ''
    while True:  # keyset-paged backfill of the rest from the JSON aggregate
        rows = conn.execute(sa.select(shipments.c.id, shipments.c.data).where(
            shipments.c.id > last_id, shipments.c.status != 'delivered').order_by(shipments.c.id).limit(500)).all()
        if not rows:
            break
        for sid, data in rows:
            d = json.loads(data)
            v = d.get('last_refresh_attempt_at') or d.get('last_refreshed_at')
            marker = datetime.fromisoformat(v.replace('Z', '+00:00')) if v else never
            conn.execute(shipments.update().where(shipments.c.id == sid).values(refresh_marker=marker))
        last_id = rows[-1][0]
    with op.batch_alter_table('shipments', schema=None) as batch_op:
        batch_op.create_index('ix_shipments_owner_created', ['owner_id', 'created_at'], unique=False)
        batch_op.create_index('ix_shipments_refresh', ['refresh_marker', 'created_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('shipments', schema=None) as batch_op:
        batch_op.drop_index('ix_shipments_refresh')
        batch_op.drop_index('ix_shipments_owner_created')
        batch_op.drop_column('refresh_marker')
