"""review queue resolutions (audit)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-16 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('review_resolutions',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('invoice_id', sa.String(length=40), nullable=False),
    sa.Column('action', sa.String(length=16), nullable=False),
    sa.Column('note', sa.String(length=500), nullable=True),
    sa.Column('reviewer', sa.String(length=64), nullable=False),
    sa.Column('previous_reason', sa.String(length=64), nullable=False),
    sa.Column('invoice_status', sa.String(length=20), nullable=False),
    sa.Column('new_reason', sa.String(length=64), nullable=False),
    sa.Column('confirm_amount_mismatch', sa.Boolean(), nullable=False),
    sa.Column('received_amount', sa.String(length=32), nullable=True),
    sa.Column('received_currency', sa.String(length=5), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('review_resolutions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_review_resolutions_invoice_id'), ['invoice_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('review_resolutions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_review_resolutions_invoice_id'))
    op.drop_table('review_resolutions')
