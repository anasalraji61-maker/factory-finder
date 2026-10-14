"""verified-deal reviews

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('reviews',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('deal_id', sa.String(length=40), nullable=False),
    sa.Column('buyer_id', sa.String(length=64), nullable=False),
    sa.Column('supplier_ref', sa.String(length=64), nullable=False),
    sa.Column('reviewer_display', sa.String(length=64), nullable=False),
    sa.Column('rating', sa.Integer(), nullable=False),
    sa.Column('quality', sa.Integer(), nullable=True),
    sa.Column('communication', sa.Integer(), nullable=True),
    sa.Column('shipping', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=80), nullable=True),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('flagged_for_review', sa.Boolean(), nullable=False),
    sa.Column('reply_text', sa.Text(), nullable=True),
    sa.Column('reply_by', sa.String(length=64), nullable=True),
    sa.Column('replied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('deal_id')
    )
    with op.batch_alter_table('reviews', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_reviews_buyer_id'), ['buyer_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_reviews_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_reviews_supplier_ref'), ['supplier_ref'], unique=False)

    op.create_table('review_events',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('review_id', sa.String(length=40), nullable=False),
    sa.Column('action', sa.String(length=12), nullable=False),
    sa.Column('actor_id', sa.String(length=64), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('review_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_review_events_review_id'), ['review_id'], unique=False)

    op.create_table('review_reports',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('review_id', sa.String(length=40), nullable=False),
    sa.Column('reporter_id', sa.String(length=64), nullable=False),
    sa.Column('reason', sa.String(length=10), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('review_id', 'reporter_id', name='uq_review_reports_review_reporter')
    )
    with op.batch_alter_table('review_reports', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_review_reports_review_id'), ['review_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_review_reports_reporter_id'), ['reporter_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('review_reports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_review_reports_reporter_id'))
        batch_op.drop_index(batch_op.f('ix_review_reports_review_id'))
    op.drop_table('review_reports')
    with op.batch_alter_table('review_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_review_events_review_id'))
    op.drop_table('review_events')
    with op.batch_alter_table('reviews', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_reviews_supplier_ref'))
        batch_op.drop_index(batch_op.f('ix_reviews_status'))
        batch_op.drop_index(batch_op.f('ix_reviews_buyer_id'))
    op.drop_table('reviews')
