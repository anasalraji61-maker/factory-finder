"""additive index for owner export ordering (owner_id, created_at)

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_media_files_owner_created', 'media_files', ['owner_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_media_files_owner_created', table_name='media_files')
