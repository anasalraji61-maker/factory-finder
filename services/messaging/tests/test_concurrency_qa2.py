"""QA pass 2: races + block privacy on a file-backed SQLite database."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from ff_messaging.config import Settings
from ff_messaging.domain.errors import MessagingError
from ff_messaging.domain.models import (
    ContextType,
    ConversationContext,
    MessageDraft,
    MessageType,
    ParticipantSpec,
    Role,
)
from ff_messaging.main import build_service, create_app
from ff_messaging.persistence.database import Database
from ff_messaging.persistence.tables import messages, user_blocks
from ff_messaging.realtime.hub import ConversationHub


@pytest.fixture
async def svc(tmp_path):
    s = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/m.db", send_rate_limit=1000, conversation_create_limit=1000)
    db = Database(s.database_url)
    await db.create_all()
    sv = build_service(s, db, ConversationHub())
    yield sv
    await db.dispose()


CTX = ConversationContext(ContextType.LISTING, "lst_1")


async def _conv(svc, me="buyer1", other="sup1"):
    conv, _ = await svc.create_conversation(
        me, participants=[ParticipantSpec(other, Role.SUPPLIER)], my_role=Role.BUYER, context=CTX, title=None
    )
    return conv.id


def _draft(text="hello there", cid=None):
    return MessageDraft(type=MessageType.TEXT, text=text, client_message_id=cid)


async def test_duplicate_client_id_stores_once(svc):
    cid = await _conv(svc)
    res = await asyncio.gather(*[svc.send_message("buyer1", cid, _draft(cid="c-1")) for _ in range(10)])
    assert sum(1 for _, created in res if created) == 1
    assert len({m.id for m, _ in res}) == 1
    async with svc.db.read() as c:
        assert await c.scalar(select(func.count()).select_from(messages)) == 1


async def test_same_client_id_different_senders_are_independent(svc):
    cid = await _conv(svc)
    res = await asyncio.gather(
        svc.send_message("buyer1", cid, _draft("a message", "x")), svc.send_message("sup1", cid, _draft("b message", "x"))
    )
    assert all(created for _, created in res)
    assert sorted(m.seq for m, _ in res) == [1, 2]


async def test_concurrent_sends_get_dense_unique_seq(svc):
    cid = await _conv(svc)
    res = await asyncio.gather(*[svc.send_message("buyer1", cid, _draft(f"msg {i}")) for i in range(12)])
    assert sorted(m.seq for m, _ in res) == list(range(1, 13))


async def test_concurrent_create_conversation_dedupes(svc):
    res = await asyncio.gather(*[_conv(svc) for _ in range(6)])
    assert len(set(res)) == 1


async def test_block_races_with_send(svc):
    cid = await _conv(svc)
    out = await asyncio.gather(
        svc.block_user("sup1", "buyer1"),
        *[svc.send_message("buyer1", cid, _draft(f"msg {i}")) for i in range(6)],
        svc.block_user("sup1", "buyer1"),
        return_exceptions=True,
    )
    assert not [o for o in out if isinstance(o, Exception) and not isinstance(o, MessagingError)], out
    async with svc.db.read() as c:
        assert await c.scalar(select(func.count()).select_from(user_blocks)) == 1  # double block = one row
    # after the block: neutral 404 for the blocked sender, no new rows
    async with svc.db.read() as c:
        before = await c.scalar(select(func.count()).select_from(messages))
    with pytest.raises(MessagingError) as e:
        await svc.send_message("buyer1", cid, _draft("late message"))
    assert e.value.code == "conversation_not_found"
    async with svc.db.read() as c:
        assert await c.scalar(select(func.count()).select_from(messages)) == before


async def test_blocker_view_is_hidden_and_blocked_sender_gets_404(svc):
    cid = await _conv(svc)
    await svc.send_message("buyer1", cid, _draft("before the block"))
    await svc.block_user("sup1", "buyer1")
    for call in (svc.get_conversation("sup1", cid), svc.list_messages("sup1", cid, cursor=None, limit=None)):
        with pytest.raises(MessagingError):
            await call
    page = await svc.list_conversations("sup1", page=1, page_size=None)
    assert page.total == 0 and page.unread_total == 0


def test_typing_frames_stop_after_block(tmp_path):
    s = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/w.db", typing_throttle_seconds=0)
    h = lambda u: {"X-User-Id": u}  # noqa: E731
    with TestClient(create_app(s)) as c:
        cid = c.post(
            "/v1/conversations", headers=h("buyer1"),
            json={"participants": [{"user_id": "sup1", "role": "supplier"}], "context": {"type": "listing", "ref_id": "lst_1"}},
        ).json()["id"]
        with c.websocket_connect(f"/v1/ws/conversations/{cid}", headers=h("sup1")) as sup_ws:
            assert sup_ws.receive_json()["type"] == "ready"
            with c.websocket_connect(f"/v1/ws/conversations/{cid}", headers=h("buyer1")) as buyer_ws:
                buyer_ws.receive_json()
                buyer_ws.send_json({"type": "typing"})
                assert sup_ws.receive_json()["type"] == "typing"
                assert c.put("/v1/blocks/buyer1", headers=h("sup1")).status_code == 204
                buyer_ws.send_json({"type": "typing"})  # blocked: must not reach the blocker
                sup_ws.send_json({"type": "ping"})
                assert sup_ws.receive_json()["type"] == "pong"
