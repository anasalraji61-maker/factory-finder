"""supplier analytics: listing_stats_daily

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('listing_stats_daily',
    sa.Column('listing_id', sa.String(length=16), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('metric', sa.String(length=16), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('uniques', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('listing_id', 'day', 'metric')
    )
    with op.batch_alter_table('listing_stats_daily', schema=None) as batch_op:
        batch_op.create_index('ix_listing_stats_daily_day', ['day'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('listing_stats_daily', schema=None) as batch_op:
        batch_op.drop_index('ix_listing_stats_daily_day')
    op.drop_table('listing_stats_daily')
