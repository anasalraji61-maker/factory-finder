"""listing moderation: status widened, moderation columns, listing_reports

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('native_listings', schema=None) as batch_op:
        batch_op.alter_column('status', existing_type=sa.String(length=10), type_=sa.String(length=16), existing_nullable=False)
        batch_op.add_column(sa.Column('moderation_source', sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column('moderation_reason', sa.String(length=400), nullable=True))
        batch_op.add_column(sa.Column('status_before', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('moderated_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table('listing_reports',
    sa.Column('id', sa.String(length=16), nullable=False),
    sa.Column('listing_id', sa.String(length=16), nullable=False),
    sa.Column('reporter_ref', sa.String(length=32), nullable=False),
    sa.Column('reason', sa.String(length=24), nullable=False),
    sa.Column('details', sa.String(length=500), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('listing_id', 'reporter_ref', name='uq_listing_reports_listing_reporter')
    )
    with op.batch_alter_table('listing_reports', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_listing_reports_listing_id'), ['listing_id'], unique=False)
        batch_op.create_index('ix_listing_reports_status_created', ['status', 'created_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('listing_reports', schema=None) as batch_op:
        batch_op.drop_index('ix_listing_reports_status_created')
        batch_op.drop_index(batch_op.f('ix_listing_reports_listing_id'))
    op.drop_table('listing_reports')
    with op.batch_alter_table('native_listings', schema=None) as batch_op:
        batch_op.drop_column('moderated_at')
        batch_op.drop_column('status_before')
        batch_op.drop_column('moderation_reason')
        batch_op.drop_column('moderation_source')
        batch_op.alter_column('status', existing_type=sa.String(length=16), type_=sa.String(length=10), existing_nullable=False)
