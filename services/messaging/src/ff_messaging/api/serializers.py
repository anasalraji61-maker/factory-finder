"""Domain -> JSON (snake_case, ISO-8601 UTC timestamps)."""

from typing import Any

from ff_messaging.domain.clock import format_utc
from ff_messaging.domain.models import (
    Conversation,
    ConversationPage,
    Message,
    MessagePage,
    ReadState,
)


def _ts(value: Any) -> str | None:
    return format_utc(value) if value is not None else None


def message_json(m: Message) -> dict[str, Any]:
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "seq": m.seq,
        "sender_id": m.sender_id,
        "type": m.type.value,
        "text": m.text,
        "attachment": (
            {
                "url": m.attachment.url,
                "mime": m.attachment.mime,
                "size": m.attachment.size,
                "name": m.attachment.name,
            }
            if m.attachment
            else None
        ),
        "offer_ref": (
            {"offer_id": m.offer_ref.offer_id, "request_id": m.offer_ref.request_id}
            if m.offer_ref
            else None
        ),
        "event": m.event,
        "event_data": m.event_data,
        "flags": list(m.flags),
        "flagged": m.flagged,
        "client_message_id": m.client_message_id,
        "created_at": _ts(m.created_at),
        "read_by": list(m.read_by),
    }


def read_state_json(s: ReadState) -> dict[str, Any]:
    return {
        "conversation_id": s.conversation_id,
        "user_id": s.user_id,
        "last_read_seq": s.last_read_seq,
        "last_read_message_id": s.last_read_message_id,
        "read_at": _ts(s.read_at),
        "unread_count": s.unread_count,
    }


def conversation_json(
    c: Conversation, viewer: str | None = None, alias: str | None = None
) -> dict[str, Any]:
    lm = c.last_message
    return {
        "id": c.id,
        "context": {"type": c.context.type.value, "ref_id": c.context.ref_id}
        if c.context
        else None,
        "title": c.title,
        "supplier_ref": c.supplier_ref,
        "created_by": c.created_by,
        "created_at": _ts(c.created_at),
        "updated_at": _ts(c.updated_at),
        "participants": [
            {
                "user_id": p.user_id,
                "role": p.role.value,
                "joined_at": _ts(p.joined_at),
                "last_read_seq": p.last_read_seq,
                "last_read_at": _ts(p.last_read_at),
            }
            for p in c.participants
        ],
        "unread_count": c.unread_count_for(viewer, alias),
        "last_message": (
            {
                "id": lm.id,
                "seq": lm.seq,
                "type": lm.type.value,
                "sender_id": lm.sender_id,
                "preview": lm.preview,
                "event": lm.event,
                "flagged": lm.flagged,
                "created_at": _ts(lm.created_at),
            }
            if lm
            else None
        ),
    }


def conversation_page_json(
    p: ConversationPage, viewer: str, alias: str | None = None
) -> dict[str, Any]:
    return {
        "items": [conversation_json(c, viewer, alias) for c in p.items],
        "total": p.total,
        "page": p.page,
        "page_size": p.page_size,
        "unread_total": p.unread_total,
    }


def message_page_json(p: MessagePage) -> dict[str, Any]:
    return {
        "items": [message_json(m) for m in p.items],
        "next_cursor": p.next_cursor,
        "has_more": p.has_more,
    }
