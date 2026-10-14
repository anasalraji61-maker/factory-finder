"""initial freight schema

Revision ID: 0001
Revises:
Create Date: 2026-10-15
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("company_name", sa.String(120), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lanes", sa.JSON(), nullable=False),
        sa.Column("modes", sa.String(40), nullable=False),
        sa.Column("incoterms", sa.String(80), nullable=False),
        sa.Column("certifications", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("review_note", sa.String(300), nullable=True),
        sa.Column("forwarder_id", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_applications_status_created", "applications", ["status", "created_at", "id"])
    op.create_index("ix_applications_user_created", "applications", ["user_id", "created_at", "id"])
    op.create_table(
        "forwarders",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("company_name", sa.String(120), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("modes", sa.String(40), nullable=False),
        sa.Column("incoterms", sa.String(80), nullable=False),
        sa.Column("certifications", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("status_reason", sa.String(300), nullable=True),
        sa.Column("rating_sum", sa.Integer(), nullable=False),
        sa.Column("rating_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_forwarders_user"),
    )
    op.create_index("ix_forwarders_status_created", "forwarders", ["status", "created_at", "id"])
    op.create_table(
        "forwarder_lanes",
        sa.Column("forwarder_id", sa.String(40), sa.ForeignKey("forwarders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("origin_country", sa.String(2), nullable=False),
        sa.Column("destination_country", sa.String(2), nullable=False),
        sa.PrimaryKeyConstraint("forwarder_id", "origin_country", "destination_country"),
    )
    op.create_index("ix_lanes_route", "forwarder_lanes", ["origin_country", "destination_country", "forwarder_id"])
    op.create_table(
        "shipment_requests",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("buyer_id", sa.String(128), nullable=False),
        sa.Column("origin_country", sa.String(2), nullable=False),
        sa.Column("origin_place", sa.String(80), nullable=False),
        sa.Column("destination_country", sa.String(2), nullable=False),
        sa.Column("destination_place", sa.String(80), nullable=False),
        sa.Column("cargo_description", sa.Text(), nullable=False),
        sa.Column("hs_code", sa.String(10), nullable=True),
        sa.Column("weight_kg", sa.String(24), nullable=True),
        sa.Column("volume_cbm", sa.String(24), nullable=True),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("container_type", sa.String(12), nullable=True),
        sa.Column("container_count", sa.Integer(), nullable=True),
        sa.Column("incoterm", sa.String(3), nullable=False),
        sa.Column("ready_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("landed_cost_ref", sa.String(64), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("visibility", sa.String(8), nullable=False),
        sa.Column("hidden_reason", sa.String(300), nullable=True),
        sa.Column("awarded_quote_id", sa.String(40), nullable=True),
        sa.Column("awarded_forwarder_id", sa.String(40), nullable=True),
        sa.Column("quote_count", sa.Integer(), nullable=False),
        sa.Column("report_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_requests_buyer_created", "shipment_requests", ["buyer_id", "created_at", "id"])
    op.create_index("ix_requests_open_route", "shipment_requests", ["status", "visibility", "origin_country", "destination_country", "created_at", "id"])
    op.create_index("ix_requests_status_expires", "shipment_requests", ["status", "expires_at"])
    op.create_table(
        "quotes",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("request_id", sa.String(40), sa.ForeignKey("shipment_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("forwarder_id", sa.String(40), sa.ForeignKey("forwarders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.String(24), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("transit_days", sa.Integer(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("inclusions", sa.JSON(), nullable=False),
        sa.Column("exclusions", sa.JSON(), nullable=False),
        sa.Column("breakdown", sa.JSON(), nullable=False),
        sa.Column("terms", sa.Text(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("visibility", sa.String(8), nullable=False),
        sa.Column("hidden_reason", sa.String(300), nullable=True),
        sa.Column("report_count", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "forwarder_id", name="uq_quotes_request_forwarder"),
    )
    op.create_index("ix_quotes_forwarder_created", "quotes", ["forwarder_id", "created_at", "id"])
    op.create_index("ix_quotes_request_created", "quotes", ["request_id", "created_at", "id"])
    op.create_table(
        "ratings",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("request_id", sa.String(40), sa.ForeignKey("shipment_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("forwarder_id", sa.String(40), sa.ForeignKey("forwarders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("buyer_id", sa.String(128), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", name="uq_ratings_request"),
    )
    op.create_index("ix_ratings_forwarder_created", "ratings", ["forwarder_id", "created_at", "id"])
    op.create_table(
        "reports",
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("target_type", sa.String(10), nullable=False),
        sa.Column("target_id", sa.String(40), nullable=False),
        sa.Column("reporter_id", sa.String(128), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("details", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_type", "target_id", "reporter_id", name="uq_reports_once"),
    )
    op.create_index("ix_reports_created", "reports", ["created_at", "id"])
    op.create_index("ix_reports_target", "reports", ["target_type", "target_id", "created_at"])
    op.create_table(
        "rate_events",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rate_user_action_created", "rate_events", ["user_id", "action", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_rate_user_action_created", table_name="rate_events")
    op.drop_table("rate_events")
    op.drop_index("ix_reports_created", table_name="reports")
    op.drop_index("ix_reports_target", table_name="reports")
    op.drop_table("reports")
    op.drop_index("ix_ratings_forwarder_created", table_name="ratings")
    op.drop_table("ratings")
    op.drop_index("ix_quotes_forwarder_created", table_name="quotes")
    op.drop_index("ix_quotes_request_created", table_name="quotes")
    op.drop_table("quotes")
    op.drop_index("ix_requests_buyer_created", table_name="shipment_requests")
    op.drop_index("ix_requests_open_route", table_name="shipment_requests")
    op.drop_index("ix_requests_status_expires", table_name="shipment_requests")
    op.drop_table("shipment_requests")
    op.drop_index("ix_lanes_route", table_name="forwarder_lanes")
    op.drop_table("forwarder_lanes")
    op.drop_index("ix_forwarders_status_created", table_name="forwarders")
    op.drop_table("forwarders")
    op.drop_index("ix_applications_status_created", table_name="applications")
    op.drop_index("ix_applications_user_created", table_name="applications")
    op.drop_table("applications")
