"""per-viewer supplier mutes

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
    op.create_table('mutes',
    sa.Column('user_id', sa.String(length=128), nullable=False),
    sa.Column('supplier_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('user_id', 'supplier_id')
    )
    with op.batch_alter_table('mutes', schema=None) as batch_op:
        batch_op.create_index('ix_mutes_user_created', ['user_id', 'created_at', 'supplier_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('mutes', schema=None) as batch_op:
        batch_op.drop_index('ix_mutes_user_created')
    op.drop_table('mutes')
