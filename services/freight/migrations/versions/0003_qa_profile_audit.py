"""Application attachments, company-name keys (duplicate detection) and the admin audit log."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from ff_freight.service_keys import name_key

    op.add_column("applications", sa.Column("attachments", sa.JSON(), nullable=True))
    op.add_column("applications", sa.Column("name_key", sa.String(160), nullable=True))
    op.add_column("forwarders", sa.Column("name_key", sa.String(160), nullable=True))
    op.create_index("ix_applications_name_key", "applications", ["name_key"])
    op.create_index("ix_forwarders_name_key", "forwarders", ["name_key"])
    bind = op.get_bind()
    for table in ("applications", "forwarders"):
        for rid, name, cc in bind.execute(sa.text(f"SELECT id, company_name, country_code FROM {table}")).all():
            bind.execute(
                sa.text(f"UPDATE {table} SET name_key = :k WHERE id = :i"), {"k": name_key(name, cc), "i": rid}
            )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("target_id", sa.String(40), nullable=False),
        sa.Column("detail", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_target", "audit_log", ["target_type", "target_id", "created_at"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_index("ix_forwarders_name_key", table_name="forwarders")
    op.drop_index("ix_applications_name_key", table_name="applications")
    op.drop_column("forwarders", "name_key")
    op.drop_column("applications", "name_key")
    op.drop_column("applications", "attachments")
