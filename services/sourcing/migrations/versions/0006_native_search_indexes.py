"""native listings: public search window indexes (status, published_at) and (status, kind, published_at)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15 12:00:00
"""
from alembic import op


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_native_listings_status_published', 'native_listings', ['status', 'published_at'], unique=False)
    op.create_index('ix_native_listings_status_kind_published', 'native_listings', ['status', 'kind', 'published_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_native_listings_status_kind_published', table_name='native_listings')
    op.drop_index('ix_native_listings_status_published', table_name='native_listings')
