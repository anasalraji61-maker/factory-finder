"""unique partial index for idempotent sends (conversation, sender, client id)

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'uq_messages_client_id',
        'messages',
        ['conversation_id', 'sender_id', 'client_message_id'],
        unique=True,
        sqlite_where=sa.text('client_message_id IS NOT NULL'),
        postgresql_where=sa.text('client_message_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_messages_client_id', table_name='messages')
