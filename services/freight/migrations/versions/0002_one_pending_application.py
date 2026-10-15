"""At most one pending application per user (closes the duplicate-submit race).

Upgrade fails loudly if a user already has several pending applications (reject the extras by hand first).
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

PENDING = "status = 'pending'"


def upgrade() -> None:
    op.create_index("uq_applications_one_pending", "applications", ["user_id"], unique=True,
                    sqlite_where=sa.text(PENDING), postgresql_where=sa.text(PENDING))


def downgrade() -> None:
    op.drop_index("uq_applications_one_pending", table_name="applications")
