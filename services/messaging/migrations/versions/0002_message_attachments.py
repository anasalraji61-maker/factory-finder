"""message attachments[] (media-service references)

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'messages',
        sa.Column('attachments', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table('messages') as batch:
        batch.drop_column('attachments')
