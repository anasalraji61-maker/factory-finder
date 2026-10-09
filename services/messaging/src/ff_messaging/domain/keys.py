"""Idempotency key for conversations: same participant set + same context = same conversation."""

import hashlib
from collections.abc import Iterable

from ff_messaging.domain.models import ConversationContext

_UNIT = "\x1f"
_RECORD = "\x1e"


def conversation_dedupe_key(user_ids: Iterable[str], context: ConversationContext | None) -> str:
    """Stable SHA-256 over the *sorted, de-duplicated* user ids and the context.

    Roles and title are deliberately not part of the key: asking twice for "the conversation
    between A and B about listing X" must always return the same conversation.
    """
    ids = sorted(set(user_ids))
    ctx = f"{context.type.value}{_UNIT}{context.ref_id or ''}" if context else "-"
    raw = f"v1{_RECORD}{_UNIT.join(ids)}{_RECORD}{ctx}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
