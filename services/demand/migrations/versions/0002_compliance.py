"""compliance: thread/author keys on drafts, permanent suppressions

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("drafts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("thread_key", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("author_key", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_drafts_thread_key"), ["thread_key"], unique=False)
        batch_op.create_index(batch_op.f("ix_drafts_author_key"), ["author_key"], unique=False)
    op.create_table(
        "suppressions",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("doc", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("suppressions")
    with op.batch_alter_table("drafts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_drafts_author_key"))
        batch_op.drop_index(batch_op.f("ix_drafts_thread_key"))
        batch_op.drop_column("author_key")
        batch_op.drop_column("thread_key")
