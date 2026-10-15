"""reports: (low_trust, status, created_at) index for the bucket count / eviction

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15 12:00:00
"""
from alembic import op


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_reports_lowtrust_status_created', 'reports', ['low_trust', 'status', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_reports_lowtrust_status_created', table_name='reports')
