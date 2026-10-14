"""media_files.visibility (public|private); dedupe unique per (owner, sha256, visibility)

Existing rows become 'public' (their bytes were already stored under public keys). Files previously uploaded as
kind=verification must be re-uploaded to become private.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-15 09:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('media_files', schema=None) as batch_op:
        batch_op.add_column(sa.Column('visibility', sa.String(length=8), server_default='public', nullable=False))
        batch_op.drop_constraint('uq_media_files_owner_sha256', type_='unique')
        batch_op.create_unique_constraint('uq_media_files_owner_sha256_vis', ['owner_id', 'sha256', 'visibility'])


def downgrade() -> None:
    # private rows would become unreachable orphans (their storage keys are 'p-' prefixed): drop them first
    op.execute("DELETE FROM media_files WHERE visibility = 'private'")
    with op.batch_alter_table('media_files', schema=None) as batch_op:
        batch_op.drop_constraint('uq_media_files_owner_sha256_vis', type_='unique')
        batch_op.create_unique_constraint('uq_media_files_owner_sha256', ['owner_id', 'sha256'])
        batch_op.drop_column('visibility')
