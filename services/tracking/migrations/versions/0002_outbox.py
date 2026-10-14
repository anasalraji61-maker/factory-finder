"""tracking_outbox: notification event records

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('tracking_outbox',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('dedupe_key', sa.String(length=200), nullable=False),
    sa.Column('shipment_id', sa.String(length=40), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('payload', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedupe_key')
    )
    with op.batch_alter_table('tracking_outbox', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tracking_outbox_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tracking_outbox_shipment_id'), ['shipment_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('tracking_outbox', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tracking_outbox_shipment_id'))
        batch_op.drop_index(batch_op.f('ix_tracking_outbox_owner_id'))
    op.drop_table('tracking_outbox')
