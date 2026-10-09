"""Domain model for conversations and messages.

Everything here is immutable and free of I/O so it can be shared by the persistence,
service, REST and WebSocket layers without coupling them to each other.

Unread counting relies on one invariant: every message with ``seq`` greater than a participant's
``last_read_seq`` was written by someone else (sending a message moves the sender's read pointer
to it). Therefore ``unread_count = conversation.last_seq - participant.last_read_seq`` exactly,
and nothing has to be incremented per recipient when a message is stored.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    """Role of a participant inside a conversation (informational; access is by membership)."""

    BUYER = "buyer"
    SUPPLIER = "supplier"
    PLATFORM = "platform"


class ContextType(StrEnum):
    """What a conversation is about."""

    LISTING = "listing"
    REQUEST = "request"
    DEAL = "deal"
    SUPPORT = "support"


class MessageType(StrEnum):
    TEXT = "text"
    ATTACHMENT = "attachment"
    OFFER_REF = "offer_ref"
    SYSTEM = "system"


class AbuseAction(StrEnum):
    """What to do with a message that matches the abuse word list."""

    FLAG = "flag"  # store and deliver unchanged, mark as flagged
    MASK = "mask"  # store and deliver with matched words masked, mark as flagged
    REJECT = "reject"  # refuse the message (422)


FLAG_ABUSIVE_LANGUAGE = "abusive_language"


@dataclass(frozen=True, slots=True)
class ConversationContext:
    type: ContextType
    ref_id: str | None  # required for listing / request / deal, optional for support


@dataclass(frozen=True, slots=True)
class ParticipantSpec:
    """A participant requested when creating a conversation."""

    user_id: str
    role: Role


@dataclass(frozen=True, slots=True)
class Participant:
    user_id: str
    role: Role
    joined_at: datetime
    last_read_seq: int = 0
    last_read_message_id: str | None = None
    last_read_at: datetime | None = None
    unread_count: int = 0


@dataclass(frozen=True, slots=True)
class LastMessage:
    """Denormalised summary of the newest message, used by conversation lists."""

    id: str
    seq: int
    type: MessageType
    sender_id: str | None
    preview: str | None
    event: str | None
    flagged: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    context: ConversationContext | None
    title: str | None
    created_by: str | None  # None when created by an internal service
    created_at: datetime
    updated_at: datetime  # last activity: creation or newest message
    last_seq: int
    participants: tuple[Participant, ...]
    last_message: LastMessage | None = None

    def participant(self, user_id: str) -> Participant | None:
        return next((p for p in self.participants if p.user_id == user_id), None)

    def is_participant(self, user_id: str) -> bool:
        return self.participant(user_id) is not None

    def unread_count_for(self, user_id: str | None) -> int:
        participant = self.participant(user_id) if user_id is not None else None
        return participant.unread_count if participant else 0


@dataclass(frozen=True, slots=True)
class Attachment:
    url: str
    mime: str
    size: int
    name: str | None = None


@dataclass(frozen=True, slots=True)
class OfferRef:
    offer_id: str
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    conversation_id: str
    seq: int  # strictly increasing per conversation, starts at 1
    sender_id: str | None  # None for system messages
    type: MessageType
    text: str | None
    created_at: datetime
    attachment: Attachment | None = None
    offer_ref: OfferRef | None = None
    event: str | None = None
    event_data: dict[str, Any] | None = None
    flags: tuple[str, ...] = ()
    client_message_id: str | None = None
    read_by: tuple[str, ...] = ()

    @property
    def flagged(self) -> bool:
        return bool(self.flags)


def compute_read_by(message: Message, participants: Iterable[Participant]) -> tuple[str, ...]:
    """Participants other than the sender whose read pointer has reached ``message``."""
    return tuple(
        p.user_id
        for p in participants
        if p.user_id != message.sender_id and p.last_read_seq >= message.seq
    )


@dataclass(frozen=True, slots=True)
class MessageDraft:
    """A user-authored message before validation."""

    type: MessageType
    text: str | None = None
    attachment: Attachment | None = None
    offer_ref: OfferRef | None = None
    client_message_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReadState:
    """A participant's read pointer (result of a mark-read, or a read receipt)."""

    conversation_id: str
    user_id: str
    last_read_seq: int
    last_read_message_id: str | None
    read_at: datetime | None
    unread_count: int


@dataclass(frozen=True, slots=True)
class ConversationPage:
    items: tuple[Conversation, ...]
    total: int
    page: int
    page_size: int
    unread_total: int


@dataclass(frozen=True, slots=True)
class MessagePage:
    items: tuple[Message, ...]  # newest first
    next_cursor: str | None
    has_more: bool
