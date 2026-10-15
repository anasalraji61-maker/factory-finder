"""price history: price_observations

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('price_observations',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('listing_id', sa.String(length=64), nullable=False),
    sa.Column('price', sa.String(length=32), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('price_observations', schema=None) as batch_op:
        batch_op.create_index('ix_price_observations_listing_time', ['listing_id', 'observed_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('price_observations', schema=None) as batch_op:
        batch_op.drop_index('ix_price_observations_listing_time')
    op.drop_table('price_observations')
