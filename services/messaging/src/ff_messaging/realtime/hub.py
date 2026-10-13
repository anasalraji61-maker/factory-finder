"""In-process WebSocket hub: per-conversation fan-out through bounded queues."""

import asyncio
from collections import defaultdict
from typing import Any

from ff_messaging.api.serializers import message_json, read_state_json
from ff_messaging.domain.clock import format_utc
from ff_messaging.domain.events import DomainEvent, MessageCreated, ReadUpdated, TypingChanged


class Connection:
    def __init__(self, user_id: str, queue_size: int) -> None:
        self.user_id = user_id
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
        self.overflowed = False

    def offer(self, payload: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            self.overflowed = True  # slow consumer: the socket loop closes it


class ConversationHub:
    """Implements the EventPublisher port."""

    def __init__(self, *, queue_size: int = 256, max_per_user: int = 20) -> None:
        self.queue_size = queue_size
        self.max_per_user = max_per_user
        self._conns: dict[str, set[Connection]] = defaultdict(set)

    def connect(self, conversation_id: str, user_id: str) -> Connection | None:
        mine = sum(1 for c in self._conns[conversation_id] if c.user_id == user_id)
        if mine >= self.max_per_user:
            return None
        conn = Connection(user_id, self.queue_size)
        self._conns[conversation_id].add(conn)
        return conn

    def disconnect(self, conversation_id: str, conn: Connection) -> None:
        group = self._conns.get(conversation_id)
        if group is not None:
            group.discard(conn)
            if not group:
                del self._conns[conversation_id]

    def count(self, conversation_id: str) -> int:
        return len(self._conns.get(conversation_id, ()))

    def broadcast(
        self, conversation_id: str, payload: dict[str, Any], *, skip: Connection | None = None
    ) -> None:
        for conn in list(self._conns.get(conversation_id, ())):
            if conn is not skip:
                conn.offer(payload)

    def publish(self, event: DomainEvent) -> None:
        if isinstance(event, MessageCreated):
            m = event.message
            self.broadcast(
                m.conversation_id, {"type": "message.created", "message": message_json(m)}
            )
        elif isinstance(event, ReadUpdated):
            s = event.state
            self.broadcast(s.conversation_id, {"type": "read.updated", "read": read_state_json(s)})
        elif isinstance(event, TypingChanged):
            self.broadcast(
                event.conversation_id,
                {
                    "type": "typing",
                    "conversation_id": event.conversation_id,
                    "user_id": event.user_id,
                    "is_typing": event.is_typing,
                    "ttl_seconds": event.ttl_seconds,
                    "at": format_utc(event.at),
                },
            )
