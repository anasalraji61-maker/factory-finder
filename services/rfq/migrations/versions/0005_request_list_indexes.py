"""request list indexes (owner/status + created_at, newest-first listing)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-14 19:00:00
"""
from alembic import op


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_requests_owner_created', 'requests', ['owner_id', 'created_at'], unique=False)
    op.create_index('ix_requests_status_created', 'requests', ['status', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_requests_status_created', table_name='requests')
    op.drop_index('ix_requests_owner_created', table_name='requests')
