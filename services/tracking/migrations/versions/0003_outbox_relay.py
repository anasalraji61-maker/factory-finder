"""tracking_outbox: relay bookkeeping (attempts, next_attempt_at, dead_at, last_error)

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
    with op.batch_alter_table('tracking_outbox', schema=None) as batch_op:
        batch_op.add_column(sa.Column('attempts', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('dead_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('last_error', sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('tracking_outbox', schema=None) as batch_op:
        batch_op.drop_column('last_error')
        batch_op.drop_column('dead_at')
        batch_op.drop_column('next_attempt_at')
        batch_op.drop_column('attempts')
