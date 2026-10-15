"""Account export / erasure (called by the gateway with the internal token; see docs/decisions/account-deletion.md).

Erasure keeps every thread for the counterparty: the user's participant row, sender ids and
``created_by`` are replaced by an irreversible tombstone, and attachment references on the
user's messages are removed. Message text stays (counterparty's record); the sender is no longer identifiable.
"""

import hashlib
from typing import Any

from sqlalchemy import select, update

from ff_messaging.persistence.database import Database
from ff_messaging.persistence.tables import conversation_participants as parts
from ff_messaging.persistence.tables import conversations as convs
from ff_messaging.persistence.tables import messages as msgs

MAX_CONVERSATIONS = 500
MAX_MESSAGES = 5000


def tombstone(user_id: str) -> str:
    return "del_" + hashlib.sha256(("ff-messaging:" + user_id).encode()).hexdigest()[:16]


async def export_user(db: Database, user_id: str) -> dict[str, Any]:
    async with db.read() as conn:
        conv_ids = [
            r[0]
            for r in (
                await conn.execute(
                    select(parts.c.conversation_id).where(parts.c.user_id == user_id).limit(MAX_CONVERSATIONS + 1)
                )
            ).all()
        ]
        truncated = len(conv_ids) > MAX_CONVERSATIONS
        conv_ids = conv_ids[:MAX_CONVERSATIONS]
        rows = (
            await conn.execute(
                select(msgs).where(msgs.c.sender_id == user_id).order_by(msgs.c.created_at).limit(MAX_MESSAGES + 1)
            )
        ).mappings().all()
        truncated = truncated or len(rows) > MAX_MESSAGES
        cs = (await conn.execute(select(convs).where(convs.c.id.in_(conv_ids)))).mappings().all() if conv_ids else []
    return {
        "truncated": truncated,
        "data": {
            "conversations": [
                {"id": c["id"], "title": c["title"], "context_type": c["context_type"],
                 "context_ref_id": c["context_ref_id"], "created_at": c["created_at"].isoformat()}
                for c in cs
            ],  # fmt: skip
            "messages_sent": [
                {"id": m["id"], "conversation_id": m["conversation_id"], "type": m["type"], "text": m["text"],
                 "attachments": m["attachments"], "created_at": m["created_at"].isoformat()}
                for m in rows[:MAX_MESSAGES]
            ],  # fmt: skip
        },
    }


async def erase_user(db: Database, user_id: str) -> dict[str, int]:
    tomb = tombstone(user_id)
    async with db.transaction() as conn:
        m = await conn.execute(
            update(msgs).where(msgs.c.sender_id == user_id).values(
                sender_id=tomb, attachment_url=None, attachment_mime=None, attachment_size=None,
                attachment_name=None, attachments=None,
            )
        )  # fmt: skip
        await conn.execute(update(convs).where(convs.c.last_message_sender_id == user_id).values(last_message_sender_id=tomb))
        await conn.execute(update(convs).where(convs.c.created_by == user_id).values(created_by=tomb))
        p = await conn.execute(
            update(parts).where(parts.c.user_id == user_id).values(user_id=tomb, unread_count=0)
        )
    return {"messages_anonymized": int(m.rowcount or 0), "participations_anonymized": int(p.rowcount or 0)}
