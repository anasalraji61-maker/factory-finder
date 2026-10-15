"""Data access for one transaction / read scope. Maps rows <-> domain objects."""

import contextlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, delete, exists, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ff_messaging.domain.models import (
    Attachment,
    ContextType,
    Conversation,
    ConversationContext,
    LastMessage,
    MediaAttachment,
    Message,
    MessageType,
    OfferRef,
    Participant,
    ParticipantSpec,
    Role,
)
from ff_messaging.persistence.tables import conversation_participants as participants_t
from ff_messaging.persistence.tables import conversations as conversations_t
from ff_messaging.persistence.tables import messages as messages_t
from ff_messaging.persistence.tables import user_blocks as blocks_t


def _to_participant(row: Mapping[str, Any], last_seq: int) -> Participant:
    return Participant(
        user_id=row["user_id"],
        role=Role(row["role"]),
        joined_at=row["joined_at"],
        last_read_seq=row["last_read_seq"],
        last_read_message_id=row["last_read_message_id"],
        last_read_at=row["last_read_at"],
        # Exact by invariant: every message after a participant's read pointer is someone else's.
        unread_count=max(last_seq - row["last_read_seq"], 0),
        muted=bool(row["muted"]),
        archived=bool(row["archived"]),
    )


def _to_conversation(
    row: Mapping[str, Any], participant_rows: Sequence[Mapping[str, Any]]
) -> Conversation:
    context = None
    if row["context_type"] is not None:
        context = ConversationContext(
            type=ContextType(row["context_type"]), ref_id=row["context_ref_id"]
        )
    last_message = None
    if row["last_message_id"] is not None:
        last_message = LastMessage(
            id=row["last_message_id"],
            seq=row["last_seq"],
            type=MessageType(row["last_message_type"]),
            sender_id=row["last_message_sender_id"],
            preview=row["last_message_preview"],
            event=row["last_message_event"],
            flagged=bool(row["last_message_flagged"]),
            created_at=row["last_message_at"],
        )
    return Conversation(
        id=row["id"],
        context=context,
        title=row["title"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_seq=row["last_seq"],
        participants=tuple(_to_participant(p, row["last_seq"]) for p in participant_rows),
        last_message=last_message,
    )


def _to_message(row: Mapping[str, Any]) -> Message:
    attachment = None
    if row["attachment_url"] is not None:
        attachment = Attachment(
            url=row["attachment_url"],
            mime=row["attachment_mime"],
            size=row["attachment_size"],
            name=row["attachment_name"],
        )
    media = tuple(
        MediaAttachment(url=a["url"], kind=a["kind"], size=a.get("size"), name=a.get("name"))
        for a in (row["attachments"] or ())
    )
    offer_ref = None
    if row["offer_id"] is not None:
        offer_ref = OfferRef(offer_id=row["offer_id"], request_id=row["offer_request_id"])
    return Message(
        id=row["id"],
        conversation_id=row["conversation_id"],
        seq=row["seq"],
        sender_id=row["sender_id"],
        type=MessageType(row["type"]),
        text=row["text"],
        created_at=row["created_at"],
        attachment=attachment,
        attachments=media,
        offer_ref=offer_ref,
        event=row["event"],
        event_data=row["event_data"],
        flags=tuple(row["flags"] or ()),
        client_message_id=row["client_message_id"],
    )


class Repository:
    """Thin query layer bound to one connection (and therefore one transaction)."""

    def __init__(self, connection: AsyncConnection) -> None:
        self.conn = connection

    # ---------------------------------------------------------------- conversations

    async def get_conversation(
        self, conversation_id: str, *, lock: bool = False
    ) -> Conversation | None:
        stmt = select(conversations_t).where(conversations_t.c.id == conversation_id)
        if lock:
            # PostgreSQL: row lock serialises writers of one conversation (sequence numbers,
            # idempotency checks). SQLite ignores FOR UPDATE; BEGIN IMMEDIATE covers it.
            stmt = stmt.with_for_update()
        row = (await self.conn.execute(stmt)).mappings().first()
        if row is None:
            return None
        participant_rows = await self._participant_rows([conversation_id])
        return _to_conversation(row, participant_rows[conversation_id])

    async def get_conversation_by_key(self, dedupe_key: str) -> Conversation | None:
        stmt = select(conversations_t).where(conversations_t.c.dedupe_key == dedupe_key)
        row = (await self.conn.execute(stmt)).mappings().first()
        if row is None:
            return None
        participant_rows = await self._participant_rows([row["id"]])
        return _to_conversation(row, participant_rows[row["id"]])

    async def _participant_rows(
        self, conversation_ids: Sequence[str]
    ) -> dict[str, list[Mapping[str, Any]]]:
        grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        if not conversation_ids:
            return grouped
        stmt = (
            select(participants_t)
            .where(participants_t.c.conversation_id.in_(list(conversation_ids)))
            .order_by(participants_t.c.conversation_id, participants_t.c.position)
        )
        for row in (await self.conn.execute(stmt)).mappings():
            grouped[row["conversation_id"]].append(row)
        return grouped

    async def insert_conversation(
        self,
        *,
        conversation_id: str,
        dedupe_key: str,
        context: ConversationContext | None,
        title: str | None,
        created_by: str | None,
        participants: Sequence[ParticipantSpec],
        now: datetime,
    ) -> None:
        await self.conn.execute(
            insert(conversations_t).values(
                id=conversation_id,
                dedupe_key=dedupe_key,
                context_type=context.type.value if context else None,
                context_ref_id=context.ref_id if context else None,
                title=title,
                created_by=created_by,
                created_at=now,
                updated_at=now,
                last_seq=0,
                last_message_flagged=False,
            )
        )
        await self.conn.execute(
            insert(participants_t),
            [
                {
                    "conversation_id": conversation_id,
                    "user_id": spec.user_id,
                    "position": position,
                    "role": spec.role.value,
                    "joined_at": now,
                    "activity_at": now,
                    "last_read_seq": 0,
                    "last_read_message_id": None,
                    "last_read_at": None,
                }
                for position, spec in enumerate(participants)
            ],
        )

    def _user_filters(
        self,
        user_id: str | Sequence[str],
        *,
        context_type: ContextType | None,
        context_ref_id: str | None,
        unread_only: bool,
        archived: bool = False,
    ) -> list[ColumnElement[bool]]:
        ids = [user_id] if isinstance(user_id, str) else list(user_id)
        filters: list[ColumnElement[bool]] = [
            participants_t.c.user_id.in_(ids),
            participants_t.c.archived.is_(archived),
            ~self._hidden_by_block(ids),
        ]
        if context_type is not None:
            filters.append(conversations_t.c.context_type == context_type.value)
        if context_ref_id is not None:
            filters.append(conversations_t.c.context_ref_id == context_ref_id)
        if unread_only:
            filters.append(conversations_t.c.last_seq > participants_t.c.last_read_seq)
        return filters

    async def list_user_conversations(
        self,
        user_id: str | Sequence[str],
        *,
        offset: int,
        limit: int,
        context_type: ContextType | None = None,
        context_ref_id: str | None = None,
        unread_only: bool = False,
        archived: bool = False,
    ) -> tuple[list[Conversation], int]:
        """The user's conversations, most recent activity first, plus the filtered total."""
        joined = participants_t.join(
            conversations_t, conversations_t.c.id == participants_t.c.conversation_id
        )
        filters = self._user_filters(
            user_id,
            context_type=context_type,
            context_ref_id=context_ref_id,
            unread_only=unread_only,
            archived=archived,
        )
        total = (
            await self.conn.execute(select(func.count()).select_from(joined).where(and_(*filters)))
        ).scalar_one()
        stmt = (
            select(conversations_t)
            .select_from(joined)
            .where(and_(*filters))
            .order_by(participants_t.c.activity_at.desc(), participants_t.c.conversation_id.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self.conn.execute(stmt)).mappings().all()
        participant_rows = await self._participant_rows([row["id"] for row in rows])
        return [_to_conversation(row, participant_rows[row["id"]]) for row in rows], int(total)

    async def count_user_conversations(self, user_id: str) -> int:
        stmt = select(func.count()).select_from(participants_t).where(participants_t.c.user_id == user_id)
        return int((await self.conn.execute(stmt)).scalar_one())

    async def unread_total(self, user_id: str | Sequence[str]) -> int:
        ids = [user_id] if isinstance(user_id, str) else list(user_id)
        joined = participants_t.join(
            conversations_t, conversations_t.c.id == participants_t.c.conversation_id
        )
        stmt = (
            select(
                func.coalesce(
                    func.sum(conversations_t.c.last_seq - participants_t.c.last_read_seq), 0
                )
            )
            .select_from(joined)
            .where(
                participants_t.c.user_id.in_(ids),
                participants_t.c.muted.is_(False),
                participants_t.c.archived.is_(False),
                ~self._hidden_by_block(ids),
            )
        )
        return int((await self.conn.execute(stmt)).scalar_one())

    @staticmethod
    def _hidden_by_block(ids: Sequence[str]) -> ColumnElement[bool]:
        """True for a direct conversation whose counterparty one of ``ids`` has blocked."""
        other = participants_t.alias("blk_other")
        count = participants_t.alias("blk_count")
        return exists(
            select(1)
            .select_from(
                other.join(
                    blocks_t,
                    and_(blocks_t.c.blocker_id.in_(list(ids)), blocks_t.c.blocked_id == other.c.user_id),
                )
            )
            .where(
                other.c.conversation_id == participants_t.c.conversation_id,
                other.c.user_id.notin_(list(ids)),
                select(func.count())
                .select_from(count)
                .where(count.c.conversation_id == participants_t.c.conversation_id)
                .correlate(participants_t)
                .scalar_subquery()
                == 2,
            )
        )

    async def set_preferences(
        self, conversation_id: str, user_id: str, *, muted: bool | None, archived: bool | None
    ) -> None:
        values: dict[str, Any] = {}
        if muted is not None:
            values["muted"] = muted
        if archived is not None:
            values["archived"] = archived
        if values:
            await self.conn.execute(
                update(participants_t)
                .where(
                    participants_t.c.conversation_id == conversation_id,
                    participants_t.c.user_id == user_id,
                )
                .values(**values)
            )

    # ---------------------------------------------------------------- blocks

    async def count_blocks(self, blocker_id: str) -> int:
        return int(
            (await self.conn.execute(
                select(func.count()).select_from(blocks_t).where(blocks_t.c.blocker_id == blocker_id)
            )).scalar_one()
        )

    async def add_block(self, blocker_id: str, blocked_id: str, now: datetime) -> None:
        existing = await self.conn.execute(
            select(blocks_t.c.blocker_id).where(
                blocks_t.c.blocker_id == blocker_id, blocks_t.c.blocked_id == blocked_id
            )
        )
        if existing.first() is None:
            # savepoint: a concurrent identical PUT that won the race is a no-op, never a 500
            with contextlib.suppress(IntegrityError):
                async with self.conn.begin_nested():
                    await self.conn.execute(
                        insert(blocks_t).values(blocker_id=blocker_id, blocked_id=blocked_id, created_at=now)
                    )

    async def remove_block(self, blocker_id: str, blocked_id: str) -> None:
        await self.conn.execute(
            delete(blocks_t).where(
                blocks_t.c.blocker_id == blocker_id, blocks_t.c.blocked_id == blocked_id
            )
        )

    async def list_blocks(self, blocker_id: str) -> list[tuple[str, datetime]]:
        rows = await self.conn.execute(
            select(blocks_t.c.blocked_id, blocks_t.c.created_at)
            .where(blocks_t.c.blocker_id == blocker_id)
            .order_by(blocks_t.c.created_at, blocks_t.c.blocked_id)
            .limit(1000)
        )
        return [(r[0], r[1]) for r in rows]

    async def has_blocked(self, blocker_ids: Sequence[str], target_id: str) -> bool:
        row = await self.conn.execute(
            select(blocks_t.c.blocker_id)
            .where(blocks_t.c.blocker_id.in_(list(blocker_ids)), blocks_t.c.blocked_id == target_id)
            .limit(1)
        )
        return row.first() is not None

    # ---------------------------------------------------------------- messages

    async def allocate_seq(self, conversation_id: str) -> int:
        stmt = (
            update(conversations_t)
            .where(conversations_t.c.id == conversation_id)
            .values(last_seq=conversations_t.c.last_seq + 1)
            .returning(conversations_t.c.last_seq)
        )
        return int((await self.conn.execute(stmt)).scalar_one())

    async def insert_message(self, message: Message, *, dedupe_key: str | None) -> None:
        await self.conn.execute(
            insert(messages_t).values(
                id=message.id,
                conversation_id=message.conversation_id,
                seq=message.seq,
                sender_id=message.sender_id,
                type=message.type.value,
                text=message.text,
                attachment_url=message.attachment.url if message.attachment else None,
                attachment_mime=message.attachment.mime if message.attachment else None,
                attachment_size=message.attachment.size if message.attachment else None,
                attachment_name=message.attachment.name if message.attachment else None,
                attachments=[
                    {"url": a.url, "kind": a.kind, "size": a.size, "name": a.name}
                    for a in message.attachments
                ]
                or None,
                offer_id=message.offer_ref.offer_id if message.offer_ref else None,
                offer_request_id=message.offer_ref.request_id if message.offer_ref else None,
                event=message.event,
                event_data=message.event_data,
                flags=list(message.flags),
                client_message_id=message.client_message_id,
                dedupe_key=dedupe_key,
                created_at=message.created_at,
            )
        )

    async def record_last_message(self, message: Message, *, preview: str | None) -> None:
        """Denormalise the newest message onto the conversation and bump list ordering."""
        await self.conn.execute(
            update(conversations_t)
            .where(conversations_t.c.id == message.conversation_id)
            .values(
                updated_at=message.created_at,
                last_message_id=message.id,
                last_message_type=message.type.value,
                last_message_sender_id=message.sender_id,
                last_message_preview=preview,
                last_message_event=message.event,
                last_message_flagged=message.flagged,
                last_message_at=message.created_at,
            )
        )
        await self.conn.execute(
            update(participants_t)
            .where(participants_t.c.conversation_id == message.conversation_id)
            .values(activity_at=message.created_at)
        )
        # a new message resurfaces an archived thread for everyone but the sender
        resurface = [
            participants_t.c.conversation_id == message.conversation_id,
            participants_t.c.archived.is_(True),
        ]
        if message.sender_id is not None:
            resurface.append(participants_t.c.user_id != message.sender_id)
        await self.conn.execute(update(participants_t).where(*resurface).values(archived=False))

    async def advance_read_pointer(
        self,
        conversation_id: str,
        user_id: str,
        *,
        seq: int,
        message_id: str,
        at: datetime,
    ) -> bool:
        """Move a read pointer forward (never backwards). True when it moved."""
        result = await self.conn.execute(
            update(participants_t)
            .where(
                participants_t.c.conversation_id == conversation_id,
                participants_t.c.user_id == user_id,
                participants_t.c.last_read_seq < seq,
            )
            .values(last_read_seq=seq, last_read_message_id=message_id, last_read_at=at)
        )
        return bool(result.rowcount)

    async def get_message(self, conversation_id: str, message_id: str) -> Message | None:
        stmt = select(messages_t).where(
            messages_t.c.id == message_id, messages_t.c.conversation_id == conversation_id
        )
        row = (await self.conn.execute(stmt)).mappings().first()
        return _to_message(row) if row is not None else None

    async def find_message_by_dedupe_key(
        self, conversation_id: str, dedupe_key: str
    ) -> Message | None:
        stmt = select(messages_t).where(
            messages_t.c.conversation_id == conversation_id,
            messages_t.c.dedupe_key == dedupe_key,
        )
        row = (await self.conn.execute(stmt)).mappings().first()
        return _to_message(row) if row is not None else None

    async def list_messages(
        self, conversation_id: str, *, before_seq: int | None, limit: int
    ) -> list[Message]:
        """Newest first; ``before_seq`` is exclusive."""
        stmt = select(messages_t).where(messages_t.c.conversation_id == conversation_id)
        if before_seq is not None:
            stmt = stmt.where(messages_t.c.seq < before_seq)
        stmt = stmt.order_by(messages_t.c.seq.desc()).limit(limit)
        return [_to_message(row) for row in (await self.conn.execute(stmt)).mappings()]
