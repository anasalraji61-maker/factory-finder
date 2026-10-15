"""native listings: external_ref for bulk import idempotency

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-15 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('native_listings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('external_ref', sa.String(length=64), nullable=True))
        batch_op.create_unique_constraint('uq_native_listings_supplier_ref', ['supplier_id', 'external_ref'])


def downgrade() -> None:
    with op.batch_alter_table('native_listings', schema=None) as batch_op:
        batch_op.drop_constraint('uq_native_listings_supplier_ref', type_='unique')
        batch_op.drop_column('external_ref')
