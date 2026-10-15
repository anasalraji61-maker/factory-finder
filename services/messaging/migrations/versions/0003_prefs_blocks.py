"""per-user muted/archived flags and user_blocks

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ('muted', 'archived'):
        op.add_column(
            'conversation_participants',
            sa.Column(col, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    op.create_table(
        'user_blocks',
        sa.Column('blocker_id', sa.String(length=64), nullable=False),
        sa.Column('blocked_id', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('blocker_id', 'blocked_id', name=op.f('pk_user_blocks')),
    )
    op.create_index('ix_user_blocks_blocked', 'user_blocks', ['blocked_id'])


def downgrade() -> None:
    op.drop_index('ix_user_blocks_blocked', table_name='user_blocks')
    op.drop_table('user_blocks')
    with op.batch_alter_table('conversation_participants') as batch:
        batch.drop_column('archived')
        batch.drop_column('muted')
