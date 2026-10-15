"""Application service: orchestrates policy, rate limit, persistence and event publishing."""

from collections.abc import Callable
from datetime import datetime

from ff_messaging.config import Settings
from ff_messaging.domain.clock import Clock, utc_now
from ff_messaging.domain.cursor import decode_cursor, encode_cursor
from ff_messaging.domain.errors import (
    ForbiddenError,
    InvalidInputError,
    LimitReachedError,
    NotFoundError,
    RateLimitedError,
)
from ff_messaging.domain.events import MessageCreated, ReadUpdated
from ff_messaging.domain.ids import CONVERSATION_PREFIX, MESSAGE_PREFIX, new_id
from ff_messaging.domain.keys import conversation_dedupe_key
from ff_messaging.domain.models import (
    ContextType,
    Conversation,
    ConversationContext,
    ConversationPage,
    Message,
    MessageDraft,
    MessagePage,
    MessageType,
    Participant,
    ParticipantSpec,
    ReadState,
    Role,
    compute_read_by,
)
from ff_messaging.domain.ports import EventPublisher
from ff_messaging.domain.rules import (
    make_preview,
    resolve_participants,
    user_message_dedupe_key,
)
from ff_messaging.domain.safety import ContentPolicy, attachments_preview
from ff_messaging.persistence.database import Database
from ff_messaging.persistence.repository import Repository
from ff_messaging.ratelimit import WindowLimiter


class MessagingService:
    def __init__(
        self,
        *,
        db: Database,
        settings: Settings,
        policy: ContentPolicy,
        limiter: WindowLimiter,
        publisher: EventPublisher,
        create_limiter: WindowLimiter | None = None,
        ws_limiter: WindowLimiter | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self.db = db
        self.settings = settings
        self.policy = policy
        self.limiter = limiter
        self.publisher = publisher
        self.clock: Callable = clock
        self.ws_limiter = ws_limiter or WindowLimiter(
            limit=settings.ws_inbound_rate_limit,
            window_seconds=settings.ws_inbound_rate_window_seconds,
        )
        self.create_limiter = create_limiter or WindowLimiter(
            limit=settings.conversation_create_limit,
            window_seconds=settings.conversation_create_window_seconds,
        )

    # ------------------------------------------------------------ conversations

    async def create_conversation(
        self,
        caller: str,
        *,
        participants: list[ParticipantSpec],
        my_role: Role | None,
        context: ConversationContext | None,
        title: str | None,
        supplier_ref: str | None = None,
    ) -> tuple[Conversation, bool]:
        if context is not None and context.type is not ContextType.SUPPORT and not context.ref_id:
            raise InvalidInputError("context.ref_id is required", code="context_ref_required")
        s = self.settings
        if supplier_ref and not any(p.user_id == supplier_ref for p in participants):
            participants = [*participants, ParticipantSpec(supplier_ref, Role.SUPPLIER)]
        specs = resolve_participants(
            caller=caller,
            requested=participants,
            my_role=my_role,
            context=context,
            platform_user_ids=s.platform_ids,
            support_user_id=s.support_user_id,
            max_participants=s.max_participants,
        )
        clean_title = self.policy.check_title(title)
        if len(specs) == 2:
            async with self.db.read() as conn:
                repo = Repository(conn)
                others = [p.user_id for p in specs if p.user_id != caller]
                for other in others:
                    if other in s.platform_ids:
                        continue
                    if await repo.has_blocked([other], caller):
                        raise NotFoundError("Conversation not found", code="conversation_not_found")
                    if await repo.has_blocked([caller], other):
                        raise InvalidInputError("Unblock this user first", code="user_blocked")
        key = conversation_dedupe_key([p.user_id for p in specs], context)
        async with self.db.transaction() as conn:
            repo = Repository(conn)
            existing = await repo.get_conversation_by_key(key)
            if existing is not None:
                return existing, False
            decision = await self.create_limiter.hit(caller)  # only brand-new conversations count
            if not decision.allowed:
                raise RateLimitedError(
                    "Too many new conversations", retry_after_seconds=decision.retry_after
                )
            cap = s.max_conversations_per_user
            if cap and caller not in s.platform_ids and await repo.count_user_conversations(caller) >= cap:
                raise LimitReachedError("Conversation limit reached", code="conversation_limit_reached")
            conv_id = new_id(CONVERSATION_PREFIX)
            await repo.insert_conversation(
                conversation_id=conv_id,
                dedupe_key=key,
                context=context,
                title=clean_title,
                created_by=caller,
                participants=specs,
                now=self.clock(),
            )
            conv = await repo.get_conversation(conv_id)
        assert conv is not None
        return conv, True

    async def get_conversation(
        self, caller: str, conversation_id: str, supplier_id: str | None = None
    ) -> Conversation:
        async with self.db.read() as conn:
            return await self._require_access(
                Repository(conn), caller, conversation_id, supplier_id=supplier_id
            )

    async def list_conversations(
        self,
        caller: str,
        *,
        page: int,
        page_size: int | None,
        context_type: ContextType | None = None,
        context_ref_id: str | None = None,
        unread_only: bool = False,
        supplier_id: str | None = None,
        archived: bool = False,
    ) -> ConversationPage:
        size = min(
            page_size or self.settings.conversations_page_size,
            self.settings.conversations_page_size_max,
        )
        async with self.db.read() as conn:
            repo = Repository(conn)
            ids = (caller, supplier_id) if supplier_id else (caller,)
            items, total = await repo.list_user_conversations(
                ids,
                offset=(page - 1) * size,
                limit=size,
                context_type=context_type,
                context_ref_id=context_ref_id,
                unread_only=unread_only,
                archived=archived,
            )
            unread = await repo.unread_total(ids)
        return ConversationPage(tuple(items), total, page, size, unread)

    # ------------------------------------------------------------ messages

    async def send_message(
        self,
        caller: str,
        conversation_id: str,
        draft: MessageDraft,
        supplier_id: str | None = None,
    ) -> tuple[Message, bool]:
        checked = self.policy.check_message(draft)
        decision = await self.limiter.hit(caller)
        if not decision.allowed:
            raise RateLimitedError("Too many messages", retry_after_seconds=decision.retry_after)
        d = checked.draft
        async with self.db.transaction() as conn:
            repo = Repository(conn)
            conv = await self._require_access(
                repo, caller, conversation_id, lock=True, supplier_id=supplier_id
            )
            caller = self._acting_id(conv, caller, supplier_id)
            if conv.is_direct:  # neutral: indistinguishable from an unknown conversation
                for p in conv.participants:
                    if (
                        p.user_id != caller
                        and p.user_id not in self.settings.platform_ids
                        and await repo.has_blocked([p.user_id], caller)
                    ):
                        raise NotFoundError("Conversation not found", code="conversation_not_found")
            msg_cap = self.settings.max_messages_per_conversation
            dedupe = (
                user_message_dedupe_key(caller, d.client_message_id)
                if d.client_message_id
                else None
            )
            if dedupe:
                prior = await repo.find_message_by_dedupe_key(conversation_id, dedupe)
                if prior is not None:
                    return self._with_read_by(prior, conv), False
            if msg_cap and conv.last_seq >= msg_cap:  # after the idempotent-retry check
                raise LimitReachedError("Conversation is full", code="conversation_full")
            seq = await repo.allocate_seq(conversation_id)
            message = Message(
                id=new_id(MESSAGE_PREFIX),
                conversation_id=conversation_id,
                seq=seq,
                sender_id=caller,
                type=d.type,
                text=d.text,
                created_at=self.clock(),
                attachment=d.attachment,
                attachments=d.attachments,
                offer_ref=d.offer_ref,
                flags=checked.flags,
                client_message_id=d.client_message_id,
            )
            await repo.insert_message(message, dedupe_key=dedupe)
            preview = make_preview(checked.preview_text, self.settings.preview_length)
            if preview is None and d.attachments:
                preview = attachments_preview(d.attachments)
            if preview is None:
                preview = f"[{d.type.value}]"
            await repo.record_last_message(message, preview=preview)
            await repo.advance_read_pointer(
                conversation_id, caller, seq=seq, message_id=message.id, at=message.created_at
            )
            conv = await repo.get_conversation(conversation_id)
        assert conv is not None
        message = self._with_read_by(message, conv)
        self.publisher.publish(MessageCreated(message))
        return message, True

    async def list_messages(
        self,
        caller: str,
        conversation_id: str,
        *,
        cursor: str | None,
        limit: int | None,
        supplier_id: str | None = None,
    ) -> MessagePage:
        size = min(limit or self.settings.messages_page_size, self.settings.messages_page_size_max)
        before = decode_cursor(cursor) if cursor else None
        async with self.db.read() as conn:
            repo = Repository(conn)
            conv = await self._require_access(
                repo, caller, conversation_id, supplier_id=supplier_id
            )
            rows = await repo.list_messages(conversation_id, before_seq=before, limit=size + 1)
        has_more = len(rows) > size
        rows = rows[:size]
        items = tuple(self._with_read_by(m, conv) for m in rows)
        next_cursor = encode_cursor(rows[-1].seq) if has_more and rows else None
        return MessagePage(items, next_cursor, has_more)

    async def mark_read(
        self,
        caller: str,
        conversation_id: str,
        message_id: str | None = None,
        supplier_id: str | None = None,
    ) -> ReadState:
        async with self.db.transaction() as conn:
            repo = Repository(conn)
            conv = await self._require_access(
                repo, caller, conversation_id, lock=True, supplier_id=supplier_id
            )
            caller = self._acting_id(conv, caller, supplier_id)
            if message_id is not None:
                target = await repo.get_message(conversation_id, message_id)
                if target is None:
                    raise NotFoundError("Message not found", code="message_not_found")
                seq, mid = target.seq, target.id
            else:
                seq, mid = conv.last_seq, (conv.last_message.id if conv.last_message else None)
            moved = False
            if mid is not None:
                moved = await repo.advance_read_pointer(
                    conversation_id, caller, seq=seq, message_id=mid, at=self.clock()
                )
            conv = await repo.get_conversation(conversation_id)
        assert conv is not None
        me = conv.participant(caller)
        assert me is not None
        state = ReadState(
            conversation_id,
            caller,
            me.last_read_seq,
            me.last_read_message_id,
            me.last_read_at,
            me.unread_count,
        )
        if moved:
            self.publisher.publish(ReadUpdated(state))
        return state

    async def unread_total(self, caller: str, supplier_id: str | None = None) -> int:
        """Badge count: unread messages in visible, non-muted, non-archived conversations."""
        async with self.db.read() as conn:
            ids = (caller, supplier_id) if supplier_id else (caller,)
            return await Repository(conn).unread_total(ids)

    async def set_preferences(
        self,
        caller: str,
        conversation_id: str,
        *,
        muted: bool | None,
        archived: bool | None,
        supplier_id: str | None = None,
    ) -> Participant:
        async with self.db.transaction() as conn:
            repo = Repository(conn)
            conv = await self._require_access(
                repo, caller, conversation_id, lock=True, supplier_id=supplier_id
            )
            actor = self._acting_id(conv, caller, supplier_id)
            await repo.set_preferences(conversation_id, actor, muted=muted, archived=archived)
            conv = await repo.get_conversation(conversation_id)
        assert conv is not None
        me = conv.participant(actor)
        assert me is not None
        return me

    # ------------------------------------------------------------ blocks

    async def block_user(self, caller: str, target: str, supplier_id: str | None = None) -> None:
        if target in (caller, supplier_id):
            raise InvalidInputError("You cannot block yourself", code="cannot_block_self")
        if target in self.settings.platform_ids:
            raise InvalidInputError("This account cannot be blocked", code="cannot_block_platform")
        async with self.db.transaction() as conn:
            repo = Repository(conn)
            # a verified supplier owner blocks as the supplier identity too (threads address sup_*)
            for blocker in (caller, supplier_id):
                if blocker:
                    await repo.add_block(blocker, target, self.clock())

    async def unblock_user(self, caller: str, target: str, supplier_id: str | None = None) -> None:
        async with self.db.transaction() as conn:
            repo = Repository(conn)
            for blocker in (caller, supplier_id):
                if blocker:
                    await repo.remove_block(blocker, target)

    async def list_blocks(self, caller: str) -> list[tuple[str, datetime]]:
        async with self.db.read() as conn:
            return await Repository(conn).list_blocks(caller)

    # ------------------------------------------------------------ helpers

    async def _require_access(
        self,
        repo: Repository,
        caller: str,
        conversation_id: str,
        *,
        lock: bool = False,
        supplier_id: str | None = None,
    ) -> Conversation:
        conv = await repo.get_conversation(conversation_id, lock=lock)
        if conv is None:
            raise NotFoundError("Conversation not found", code="conversation_not_found")
        if not (conv.is_participant(caller) or (supplier_id and conv.is_participant(supplier_id))):
            raise ForbiddenError("You are not a participant of this conversation")
        if conv.is_direct:  # threads with someone the caller blocked are hidden
            mine = [x for x in (caller, supplier_id) if x and conv.is_participant(x)]
            for p in conv.participants:
                if p.user_id not in mine and await repo.has_blocked(mine, p.user_id):
                    raise NotFoundError("Conversation not found", code="conversation_not_found")
        return conv

    @staticmethod
    def _acting_id(conv: Conversation, caller: str, supplier_id: str | None) -> str:
        """Participant id the caller acts as: themselves, else their claimed supplier id."""
        if conv.is_participant(caller) or not supplier_id:
            return caller
        return supplier_id

    @staticmethod
    def _with_read_by(message: Message, conv: Conversation) -> Message:
        from dataclasses import replace

        return replace(message, read_by=compute_read_by(message, conv.participants))

    async def check_access(
        self, caller: str, conversation_id: str, supplier_id: str | None = None
    ) -> Conversation:
        return await self.get_conversation(caller, conversation_id, supplier_id)


__all__ = ["MessagingService", "MessageType"]
