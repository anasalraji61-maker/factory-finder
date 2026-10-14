"""deal lifecycle: payment state, delivery timestamps, immutable deal event log

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-14 15:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('deals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payment_state', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table('deal_events',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('deal_id', sa.String(length=40), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('from_status', sa.String(length=20), nullable=True),
    sa.Column('to_status', sa.String(length=20), nullable=True),
    sa.Column('event_id', sa.String(length=128), nullable=True),
    sa.Column('data', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('deal_id', 'seq', name='uq_deal_events_deal_seq'),
    sa.UniqueConstraint('event_id')
    )
    with op.batch_alter_table('deal_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_deal_events_deal_id'), ['deal_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('deal_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_deal_events_deal_id'))
    op.drop_table('deal_events')
    with op.batch_alter_table('deals', schema=None) as batch_op:
        batch_op.drop_column('completed_at')
        batch_op.drop_column('delivered_at')
        batch_op.drop_column('payment_state')
