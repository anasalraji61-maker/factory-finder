"""initial: verification documents, append-only audit, reports, score snapshots, meta

Revision ID: 0001
Revises:
Create Date: 2026-10-15 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

DOC_TYPES = "'business_license','company_registry_reference','bank_reference','export_license','factory_photos','iso_certificate','other_certificate'"
ACTIONS = "'submit','approve','reject','revoke','withdraw','set_expiry'"
LIVE = "status IN ('pending','approved') AND number_fingerprint IS NOT NULL"


def upgrade() -> None:
    op.create_table('verification_documents',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('supplier_id', sa.String(length=128), nullable=False),
        sa.Column('doc_type', sa.String(length=32), nullable=False),
        sa.Column('issuing_country', sa.String(length=2), nullable=False),
        sa.Column('files', sa.JSON(), nullable=False),
        sa.Column('number_masked', sa.String(length=16), nullable=True),
        sa.Column('number_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('expires_on', sa.Date(), nullable=True),
        sa.Column('consent', sa.Boolean(), nullable=False),
        sa.Column('status', sa.String(length=12), server_default='pending', nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.String(length=80), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_on', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"doc_type IN ({DOC_TYPES})", name='ck_verification_documents_doc_type'),
        sa.CheckConstraint('length(issuing_country) = 2', name='ck_verification_documents_country'),
        sa.CheckConstraint('consent', name='ck_verification_documents_consent'),
        sa.CheckConstraint("status IN ('pending','approved','rejected','withdrawn')", name='ck_verification_documents_status'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_verification_documents_supplier', 'verification_documents', ['supplier_id', 'status'], unique=False)
    op.create_index('ix_verification_documents_status', 'verification_documents', ['status', 'created_at'], unique=False)
    op.create_index('ix_verification_documents_fingerprint', 'verification_documents', ['number_fingerprint'], unique=False)
    op.create_index('uq_verification_documents_live_fingerprint', 'verification_documents', ['supplier_id', 'number_fingerprint'],
                    unique=True, sqlite_where=sa.text(LIVE), postgresql_where=sa.text(LIVE))

    op.create_table('verification_audit',
        sa.Column('seq', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actor', sa.String(length=100), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('document_id', sa.String(length=40), nullable=False),
        sa.Column('supplier_id', sa.String(length=128), nullable=False),
        sa.Column('from_status', sa.String(length=12), nullable=True),
        sa.Column('to_status', sa.String(length=12), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.CheckConstraint(f"action IN ({ACTIONS})", name='ck_verification_audit_action'),
        sa.PrimaryKeyConstraint('seq'),
    )
    op.create_index('ix_verification_audit_document', 'verification_audit', ['document_id', 'seq'], unique=False)
    op.create_index('ix_verification_audit_supplier', 'verification_audit', ['supplier_id', 'action', 'at'], unique=False)
    # append-only is enforced by the database, not only by the API
    dialect = op.get_bind().dialect.name
    if dialect == 'sqlite':
        op.execute("CREATE TRIGGER trg_verification_audit_no_update BEFORE UPDATE ON verification_audit BEGIN SELECT RAISE(ABORT, 'verification_audit is append-only'); END")
        op.execute("CREATE TRIGGER trg_verification_audit_no_delete BEFORE DELETE ON verification_audit BEGIN SELECT RAISE(ABORT, 'verification_audit is append-only'); END")
    elif dialect == 'postgresql':
        op.execute("CREATE OR REPLACE FUNCTION ff_trust_audit_append_only() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'verification_audit is append-only'; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER trg_verification_audit_append_only BEFORE UPDATE OR DELETE ON verification_audit FOR EACH ROW EXECUTE FUNCTION ff_trust_audit_append_only()")

    op.create_table('reports',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('supplier_id', sa.String(length=128), nullable=False),
        sa.Column('reporter_id', sa.String(length=128), nullable=False),
        sa.Column('type', sa.String(length=24), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='pending_review', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending_review','accepted','rejected')", name='ck_reports_status'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_reports_supplier_status', 'reports', ['supplier_id', 'status'], unique=False)
    op.create_index('ix_reports_reporter_created', 'reports', ['reporter_id', 'created_at'], unique=False)
    op.create_index('ix_reports_status_created', 'reports', ['status', 'created_at'], unique=False)

    op.create_table('score_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('supplier_id', sa.String(length=128), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('band', sa.String(length=12), nullable=False),
        sa.Column('confidence', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_score_snapshots_supplier_at', 'score_snapshots', ['supplier_id', 'at'], unique=False)
    op.create_index('ix_score_snapshots_at', 'score_snapshots', ['at'], unique=False)

    op.create_table('trust_meta',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )


def downgrade() -> None:
    op.drop_table('trust_meta')
    op.drop_index('ix_score_snapshots_at', table_name='score_snapshots')
    op.drop_index('ix_score_snapshots_supplier_at', table_name='score_snapshots')
    op.drop_table('score_snapshots')
    op.drop_index('ix_reports_status_created', table_name='reports')
    op.drop_index('ix_reports_reporter_created', table_name='reports')
    op.drop_index('ix_reports_supplier_status', table_name='reports')
    op.drop_table('reports')
    dialect = op.get_bind().dialect.name
    if dialect == 'postgresql':
        op.execute("DROP TRIGGER IF EXISTS trg_verification_audit_append_only ON verification_audit")
        op.execute("DROP FUNCTION IF EXISTS ff_trust_audit_append_only()")
    op.drop_index('ix_verification_audit_supplier', table_name='verification_audit')
    op.drop_index('ix_verification_audit_document', table_name='verification_audit')
    op.drop_table('verification_audit')  # sqlite triggers are dropped with the table
    op.drop_index('uq_verification_documents_live_fingerprint', table_name='verification_documents')
    op.drop_index('ix_verification_documents_fingerprint', table_name='verification_documents')
    op.drop_index('ix_verification_documents_status', table_name='verification_documents')
    op.drop_index('ix_verification_documents_supplier', table_name='verification_documents')
    op.drop_table('verification_documents')
