"""sweep + review list indexes (requests status/deadline, offers status/valid_until and request/status,
reviews supplier/status/created and rating)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-15 12:00:00
"""
from alembic import op


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

INDEXES = [
    ('ix_requests_status_deadline', 'requests', ['status', 'deadline']),
    ('ix_offers_status_valid_until', 'offers', ['status', 'valid_until']),
    ('ix_offers_request_status', 'offers', ['request_id', 'status']),
    ('ix_reviews_supplier_status_created', 'reviews', ['supplier_ref', 'status', 'created_at']),
    ('ix_reviews_supplier_status_rating', 'reviews', ['supplier_ref', 'status', 'rating', 'created_at']),
]


def upgrade() -> None:
    for name, table, cols in INDEXES:
        op.create_index(name, table, cols, unique=False)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
