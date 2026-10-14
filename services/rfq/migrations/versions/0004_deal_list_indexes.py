"""deal list indexes (buyer/supplier + created_at, newest-first listing)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-14 18:00:00
"""
from alembic import op


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_deals_buyer_created', 'deals', ['buyer_id', 'created_at'], unique=False)
    op.create_index('ix_deals_supplier_created', 'deals', ['supplier_user_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_deals_supplier_created', table_name='deals')
    op.drop_index('ix_deals_buyer_created', table_name='deals')
