"""invite-only requests (request_invites)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15 09:00:00
"""
import sqlalchemy as sa
from alembic import op


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'request_invites',
        sa.Column('request_id', sa.String(length=40), sa.ForeignKey('requests.id'), nullable=False),
        sa.Column('supplier_id', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('request_id', 'supplier_id'),
    )
    op.create_index('ix_request_invites_supplier_id', 'request_invites', ['supplier_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_request_invites_supplier_id', table_name='request_invites')
    op.drop_table('request_invites')
