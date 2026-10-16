"""QA: bilingual error texts and unread-counter consistency across block/unblock/erasure."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ff_messaging import i18n

from .test_inbox_state import H, make_client, new_conv, send, total

ARABIC = re.compile(r"[؀-ۿ]")
ARABIC_INDIC = re.compile(r"[٠-٩۰-۹]")
SRC = Path(__file__).resolve().parents[1] / "src" / "ff_messaging"
TOK = {"X-Internal-Token": "s3cret"}


def _codes() -> set[str]:
    codes: set[str] = set()
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        codes |= set(re.findall(r"code=\"([a-z_]+)\"", text))
        codes |= set(re.findall(r"^\s+code = \"([a-z_]+)\"", text, re.M))
        codes |= set(re.findall(r"\"code\": \"([a-z_]+)\"", text))
    return codes | {"validation_error", "not_found", "http_error", "rate_limited"}


@pytest.mark.parametrize("code", sorted(_codes()))
def test_every_error_code_has_arabic(code):
    ar = i18n.ERRORS_AR.get(code)
    assert ar and ARABIC.search(ar), code
    assert not ARABIC_INDIC.search(ar)


def test_error_envelope_has_message_ar():
    with make_client() as c:
        resps = [
            c.get("/v1/conversations"),  # unauthenticated
            c.get("/v1/conversations/conv_nope", headers=H("u1")),  # not found
            c.put("/v1/blocks/u1", headers=H("u1")),  # cannot_block_self
            c.get("/no/such/route"),  # starlette 404
            c.post("/v1/conversations", headers=H("u1"), json={}),  # validation
        ]
    for r in resps:
        err = r.json()["error"]
        assert err["message"] and ARABIC.search(err["message_ar"]), r.text


# ------------------------------------------------------------------ unread consistency


def consistent(c, who):
    """Badge == sum of per-thread unread over visible, non-muted, non-archived threads."""
    items = c.get("/v1/conversations", headers=H(who)).json()["items"]
    t = total(c, who)
    assert t == sum(i["unread_count"] for i in items if not i.get("muted")), (t, items)
    return t


@pytest.fixture
def client():
    with make_client(send_rate_limit=1000, internal_token="s3cret") as c:
        c.headers.update(TOK)
        yield c


def test_block_unblock_keeps_unread_consistent(client):
    a = new_conv(client, ref="l1")["id"]
    b = new_conv(client, me="buyer2", other="sup1", ref="l2")["id"]
    send(client, a, "buyer1")
    send(client, a, "buyer1")
    send(client, b, "buyer2")
    assert consistent(client, "sup1") == 3
    client.put("/v1/blocks/buyer1", headers=H("sup1"))
    assert consistent(client, "sup1") == 1  # only buyer2's thread counts
    # blocked sender cannot add unread behind the block
    assert client.post(f"/v1/conversations/{a}/messages", headers=H("buyer1"), json={"text": "x"}).status_code == 404
    # blocker cannot move the read pointer of a hidden thread
    assert client.post(f"/v1/conversations/{a}/read", headers=H("sup1"), json={}).status_code in (404, 422, 405)
    client.put("/v1/blocks/buyer1", headers=H("sup1"))  # idempotent
    assert consistent(client, "sup1") == 1
    client.delete("/v1/blocks/buyer1", headers=H("sup1"))
    client.delete("/v1/blocks/buyer1", headers=H("sup1"))  # idempotent
    assert consistent(client, "sup1") == 3  # nothing lost, nothing double counted
    assert consistent(client, "buyer1") == 0
    send(client, a, "buyer1")
    assert consistent(client, "sup1") == 4


def test_erasure_keeps_counterparty_unread_consistent(client):
    a = new_conv(client, ref="l1")["id"]
    b = new_conv(client, me="buyer2", other="sup1", ref="l2")["id"]
    send(client, a, "buyer1")
    send(client, b, "buyer2")
    send(client, b, "sup1")
    assert consistent(client, "sup1") == 1
    assert consistent(client, "buyer2") == 1
    # sup1 blocks buyer1; buyer1 is then erased (the block row is removed with the account)
    client.put("/v1/blocks/buyer1", headers=H("sup1"))
    assert consistent(client, "sup1") == 0
    assert client.delete("/v1/internal/users/buyer1/data", headers=TOK).status_code == 200
    assert client.delete("/v1/internal/users/buyer1/data", headers=TOK).status_code == 200
    n = consistent(client, "sup1")
    assert n == 0  # still hidden: the block survives the erasure
    assert consistent(client, "buyer2") == 1
    # the erased account has no threads and zero badge
    assert total(client, "buyer1") == 0
    # tombstoned participant never leaks into counterparty totals when they keep writing
    send(client, b, "buyer2")
    assert consistent(client, "sup1") == n + 1


def test_erasing_blocker_does_not_resurrect_unread_for_blocked_user(client):
    a = new_conv(client, ref="l1")["id"]
    send(client, a, "sup1", "hello")
    assert consistent(client, "buyer1") == 1
    client.put("/v1/blocks/sup1", headers=H("buyer1"))
    assert consistent(client, "buyer1") == 0
    client.delete("/v1/internal/users/sup1/data", headers=TOK)
    assert consistent(client, "buyer1") == 0  # block re-pointed at the tombstone
