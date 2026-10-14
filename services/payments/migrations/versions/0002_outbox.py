"""outbox for rfq deal callbacks

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14 15:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('outbox_events',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('event_id', sa.String(length=128), nullable=False),
    sa.Column('deal_id', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id')
    )
    with op.batch_alter_table('outbox_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_outbox_events_deal_id'), ['deal_id'], unique=False)
        batch_op.create_index('ix_outbox_events_status_next', ['status', 'next_attempt_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('outbox_events', schema=None) as batch_op:
        batch_op.drop_index('ix_outbox_events_status_next')
        batch_op.drop_index(batch_op.f('ix_outbox_events_deal_id'))
    op.drop_table('outbox_events')
