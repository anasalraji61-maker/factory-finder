"""digest e-mail ownership verification (hashed codes, attempts, send limits)

Legacy ``notification_prefs.doc["email"]`` values were never verified; they are ignored by the
application (the digest only goes to ``digest_email``), so no data rewrite is needed.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_verifications",
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("doc", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("owner_id"),
    )


def downgrade() -> None:
    op.drop_table("email_verifications")
