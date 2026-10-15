"""REST + WebSocket routes (thin: validation and serialisation only)."""

import hmac
import json
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel, ConfigDict, Field

from ff_messaging import privacy
from ff_messaging.api.serializers import (
    conversation_json,
    conversation_page_json,
    message_json,
    message_page_json,
    read_state_json,
)
from ff_messaging.domain.clock import format_utc, utc_now
from ff_messaging.domain.errors import (
    ForbiddenError,
    MessagingError,
    NotFoundError,
    UnauthenticatedError,
)
from ff_messaging.domain.events import TypingChanged
from ff_messaging.domain.ids import EXTERNAL_ID_PATTERN, USER_ID_PATTERN, is_valid_user_id
from ff_messaging.domain.models import (
    Attachment,
    ContextType,
    ConversationContext,
    MediaAttachment,
    MessageDraft,
    MessageType,
    OfferRef,
    ParticipantSpec,
    Role,
)
from ff_messaging.service import MessagingService

router = APIRouter(prefix="/v1")


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParticipantIn(_Body):
    user_id: str = Field(pattern=USER_ID_PATTERN)
    role: Role = Role.SUPPLIER


class ContextIn(_Body):
    type: ContextType
    ref_id: str | None = Field(default=None, pattern=EXTERNAL_ID_PATTERN)


class ConversationCreate(_Body):
    participants: list[ParticipantIn] = Field(default_factory=list, max_length=100)
    my_role: Role | None = None
    context: ContextIn | None = None
    title: str | None = None
    supplier_ref: str | None = Field(default=None, pattern=r"^sup_[A-Za-z0-9_.:\-]{1,59}$")


class AttachmentIn(_Body):
    url: str
    mime: str
    size: int
    name: str | None = None


class MediaAttachmentIn(_Body):
    url: str
    kind: Literal["image", "document"]
    size: int | None = None
    name: str | None = None


class OfferRefIn(_Body):
    offer_id: str = Field(pattern=EXTERNAL_ID_PATTERN)
    request_id: str | None = Field(default=None, pattern=EXTERNAL_ID_PATTERN)


class MessageCreate(_Body):
    type: Literal["text", "attachment", "offer_ref"] = "text"
    text: str | None = None
    attachment: AttachmentIn | None = None
    attachments: list[MediaAttachmentIn] = Field(default_factory=list, max_length=20)
    offer_ref: OfferRefIn | None = None
    client_message_id: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$"
    )


class PreferencesIn(_Body):
    muted: bool | None = None
    archived: bool | None = None


class ReadIn(_Body):
    message_id: str | None = None


def get_service(request: Request) -> MessagingService:
    return request.app.state.service


def current_user(
    request: Request,
    x_user_id: Annotated[str | None, Header()] = None,
    x_internal_token: Annotated[str | None, Header()] = None,
) -> str:
    token = request.app.state.service.settings.internal_token_value
    if token is not None and not hmac.compare_digest((x_internal_token or "").encode(), (token).encode()):
        raise UnauthenticatedError("Invalid internal token")
    if not x_user_id or not is_valid_user_id(x_user_id):
        raise UnauthenticatedError("X-User-Id header is required")
    return x_user_id


def supplier_claim(
    _user: Annotated[str, Depends(current_user)],
    x_supplier_id: Annotated[str | None, Header()] = None,
) -> str | None:
    """Supplier id the gateway verified for the caller (never client-supplied; the internal
    token check in ``current_user`` guards this header when a token is configured)."""
    if x_supplier_id and is_valid_user_id(x_supplier_id) and x_supplier_id.startswith("sup_"):
        return x_supplier_id
    return None


def privacy_guard(request: Request, x_internal_token: Annotated[str | None, Header()] = None) -> None:
    """Export/erasure are internal-only: anything but the internal token looks like a missing route."""
    token = request.app.state.service.settings.internal_token_value
    if token is not None and not hmac.compare_digest((x_internal_token or "").encode(), token.encode()):
        raise NotFoundError("Route not found")


User = Annotated[str, Depends(current_user)]
Supplier = Annotated[str | None, Depends(supplier_claim)]
Service = Annotated[MessagingService, Depends(get_service)]


@router.post("/conversations", status_code=201)
async def create_conversation(
    body: ConversationCreate, user: User, svc: Service, response: Response
) -> dict[str, Any]:
    context = ConversationContext(body.context.type, body.context.ref_id) if body.context else None
    conv, created = await svc.create_conversation(
        user,
        participants=[ParticipantSpec(p.user_id, p.role) for p in body.participants],
        my_role=body.my_role,
        context=context,
        title=body.title,
        supplier_ref=body.supplier_ref,
    )
    if not created:
        response.status_code = 200
    return conversation_json(conv, user)


@router.get("/conversations")
async def list_conversations(
    user: User,
    svc: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int | None, Query(ge=1)] = None,
    context_type: ContextType | None = None,
    context_ref_id: str | None = None,
    unread_only: bool = False,
    archived: bool = False,
    supplier: Supplier = None,
) -> dict[str, Any]:
    result = await svc.list_conversations(
        user,
        page=page,
        page_size=page_size,
        context_type=context_type,
        context_ref_id=context_ref_id,
        unread_only=unread_only,
        archived=archived,
        supplier_id=supplier,
    )
    return conversation_page_json(result, user, supplier)


@router.get("/conversations/unread-total")
async def unread_total(user: User, svc: Service, supplier: Supplier) -> dict[str, Any]:
    return {"unread_total": await svc.unread_total(user, supplier)}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str, user: User, svc: Service, supplier: Supplier
) -> dict[str, Any]:
    conv = await svc.get_conversation(user, conversation_id, supplier)
    return conversation_json(conv, user, supplier)


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    user: User,
    svc: Service,
    supplier: Supplier,
    cursor: str | None = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    return message_page_json(
        await svc.list_messages(
            user, conversation_id, cursor=cursor, limit=limit, supplier_id=supplier
        )
    )


@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def send_message(
    conversation_id: str,
    body: MessageCreate,
    user: User,
    svc: Service,
    response: Response,
    supplier: Supplier,
) -> dict[str, Any]:
    draft = MessageDraft(
        type=MessageType(body.type),
        text=body.text,
        attachment=Attachment(**body.attachment.model_dump()) if body.attachment else None,
        attachments=tuple(MediaAttachment(**a.model_dump()) for a in body.attachments),
        offer_ref=OfferRef(**body.offer_ref.model_dump()) if body.offer_ref else None,
        client_message_id=body.client_message_id,
    )
    message, created = await svc.send_message(user, conversation_id, draft, supplier)
    if not created:
        response.status_code = 200
    return message_json(message)


@router.post("/conversations/{conversation_id}/read")
async def mark_read(
    conversation_id: str, user: User, svc: Service, supplier: Supplier, body: ReadIn | None = None
) -> dict[str, Any]:
    state = await svc.mark_read(user, conversation_id, body.message_id if body else None, supplier)
    return read_state_json(state)


@router.put("/conversations/{conversation_id}/preferences")
async def set_preferences(
    conversation_id: str, body: PreferencesIn, user: User, svc: Service, supplier: Supplier
) -> dict[str, Any]:
    me = await svc.set_preferences(
        user, conversation_id, muted=body.muted, archived=body.archived, supplier_id=supplier
    )
    return {"conversation_id": conversation_id, "muted": me.muted, "archived": me.archived}


@router.get("/blocks")
async def list_blocks(user: User, svc: Service) -> dict[str, Any]:
    return {
        "items": [
            {"user_id": uid, "blocked_at": format_utc(at)} for uid, at in await svc.list_blocks(user)
        ]
    }


@router.put("/blocks/{blocked_user_id}", status_code=204)
async def block_user(
    blocked_user_id: str, user: User, svc: Service, supplier: Supplier
) -> Response:
    if not is_valid_user_id(blocked_user_id):
        raise NotFoundError("Route not found")
    await svc.block_user(user, blocked_user_id, supplier)
    return Response(status_code=204)


@router.delete("/blocks/{blocked_user_id}", status_code=204)
async def unblock_user(
    blocked_user_id: str, user: User, svc: Service, supplier: Supplier
) -> Response:
    await svc.unblock_user(user, blocked_user_id, supplier)
    return Response(status_code=204)


@router.websocket("/ws/conversations/{conversation_id}")
async def conversation_socket(
    websocket: WebSocket, conversation_id: str, user_id: str | None = None
) -> None:
    app = websocket.app
    svc: MessagingService = app.state.service
    hub = app.state.hub
    settings = svc.settings
    uid = websocket.headers.get("x-user-id")
    if uid is None and settings.query_user_id_allowed:
        uid = user_id
    try:
        if not uid or not is_valid_user_id(uid):
            raise UnauthenticatedError("user required")
        token = settings.internal_token_value
        if token is not None and not hmac.compare_digest((websocket.headers.get("x-internal-token", "")).encode(), (token).encode()):
            raise UnauthenticatedError("bad token")
        sup = websocket.headers.get("x-supplier-id")
        sup = sup if sup and sup.startswith("sup_") and is_valid_user_id(sup) else None
        conv = await svc.check_access(uid, conversation_id, sup)
        if not conv.is_participant(uid):
            uid = sup or uid
    except UnauthenticatedError:
        await websocket.close(code=4401)
        return
    except (ForbiddenError, MessagingError):
        await websocket.close(code=4403)
        return
    conn = hub.connect(conversation_id, uid)
    if conn is None:
        await websocket.close(code=4429)
        return
    await websocket.accept()
    import asyncio

    async def pump() -> None:
        while True:
            payload = await conn.queue.get()
            await websocket.send_text(json.dumps(payload, ensure_ascii=False))
            if conn.overflowed:
                await websocket.close(code=1013)
                return

    sender = asyncio.create_task(pump())
    try:
        await websocket.send_text(
            json.dumps({"type": "ready", "conversation_id": conversation_id, "user_id": uid})
        )
        while True:
            raw = await websocket.receive_text()
            ws_decision = await svc.ws_limiter.hit(uid)
            if not ws_decision.allowed:  # inbound frame flood: drop the frame, keep the socket
                conn.offer({"type": "error", "code": "rate_limited", "message": "Too many frames"})
                continue
            try:
                frame = json.loads(raw) if len(raw) <= settings.ws_max_frame_chars else {}
            except ValueError:
                frame = {}
            kind = frame.get("type") if isinstance(frame, dict) else None
            if kind == "ping":
                conn.offer({"type": "pong"})
            elif kind == "typing":
                is_typing = bool(frame.get("is_typing", True))
                if app.state.typing.should_broadcast(f"{conversation_id}:{uid}", is_typing):
                    hub.publish(
                        TypingChanged(
                            conversation_id, uid, is_typing, settings.typing_ttl_seconds, utc_now()
                        )
                    )
            elif kind == "read":
                try:
                    mid = frame.get("message_id")
                    await svc.mark_read(
                        uid, conversation_id, mid if isinstance(mid, str) and len(mid) <= 64 else None
                    )
                except MessagingError as exc:
                    conn.offer({"type": "error", "code": exc.code, "message": exc.message})
            else:
                conn.offer(
                    {"type": "error", "code": "unknown_frame", "message": "Unsupported frame"}
                )
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        hub.disconnect(conversation_id, conn)


@router.post("/internal/users/{user_id}/export", dependencies=[Depends(privacy_guard)])
async def export_user(user_id: str, svc: Service) -> dict[str, Any]:
    return {"service": "messaging", "user_id": user_id, **await privacy.export_user(svc.db, user_id)}


@router.delete("/internal/users/{user_id}/data", dependencies=[Depends(privacy_guard)])
async def erase_user(user_id: str, svc: Service) -> dict[str, Any]:
    return {"service": "messaging", "user_id": user_id, "status": "done",
            "counts": await privacy.erase_user(svc.db, user_id)}  # fmt: skip
