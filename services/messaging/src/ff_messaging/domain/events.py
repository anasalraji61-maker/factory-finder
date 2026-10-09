"""Domain events published to connected clients after a transaction commits."""

from dataclasses import dataclass
from datetime import datetime

from ff_messaging.domain.models import Message, ReadState


@dataclass(frozen=True, slots=True)
class MessageCreated:
    message: Message


@dataclass(frozen=True, slots=True)
class ReadUpdated:
    state: ReadState


@dataclass(frozen=True, slots=True)
class TypingChanged:
    conversation_id: str
    user_id: str
    is_typing: bool
    ttl_seconds: int
    at: datetime


DomainEvent = MessageCreated | ReadUpdated | TypingChanged
