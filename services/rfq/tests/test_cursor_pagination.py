"""Keyset pagination on GET /v1/requests?scope=public."""

import base64
import json

import pytest
from conftest import BUYER, new_request

VIEWER = {"X-User-Id": "viewer1"}


def _feed(client, **params):
    return client.get("/v1/requests", params={"scope": "public", **params}, headers=VIEWER)


def _walk(client, size, on_page=None):
    ids, cursor, n = [], None, 0
    while True:
        r = _feed(client, page_size=size, **({"cursor": cursor} if cursor else {}))
        assert r.status_code == 200, r.text
        body = r.json()
        ids += [i["id"] for i in body["items"]]
        n += 1
        if on_page:
            on_page(n)
        cursor = body["next_cursor"]
        if not cursor:
            return ids


def _seed(client, clock, n):
    for i in range(n):
        if i % 3:  # some rows share a created_at (tie-break by id)
            clock.advance(seconds=1)
        new_request(client, title=f"item {i}")


def test_no_cursor_is_page_mode_and_bootstraps_cursor(client, clock):
    _seed(client, clock, 5)
    body = _feed(client, page=2, page_size=2).json()
    assert (body["page"], body["page_size"], body["total"], len(body["items"])) == (2, 2, 5, 2)
    assert body["next_cursor"]
    last = _feed(client, page=3, page_size=2).json()
    assert len(last["items"]) == 1 and last["next_cursor"] is None


def test_cursor_walk_matches_page_order_no_dupes(client, clock):
    _seed(client, clock, 11)
    full = [i["id"] for i in _feed(client, page_size=100).json()["items"]]
    walked = _walk(client, 3)
    assert walked == full and len(set(walked)) == 11


def test_exact_multiple_ends_with_null_cursor(client, clock):
    _seed(client, clock, 4)
    body = _feed(client, page_size=2).json()
    body2 = _feed(client, page_size=2, cursor=body["next_cursor"]).json()
    assert len(body2["items"]) == 2 and body2["next_cursor"] is None


def test_insert_between_pages_no_dupes_no_skips(client, clock):
    _seed(client, clock, 6)
    first = _feed(client, page_size=3).json()
    clock.advance(seconds=10)
    for i in range(2):  # newer rows land at the head after page 1 was served
        new_request(client, title=f"late {i}")
    rest = _feed(client, page_size=3, cursor=first["next_cursor"]).json()
    seen = [i["id"] for i in first["items"]] + [i["id"] for i in rest["items"]]
    assert len(seen) == len(set(seen)) == 6  # offset paging would have repeated page-1 rows
    assert rest["next_cursor"] is None


def test_malformed_cursors_422(client):
    def b64(s):
        return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")

    bad = ["!!!", "abc", b64("notjson"), b64('{"a":1}'), b64('["2026-10-01T12:00:00+00:00"]'),
           b64('["nope","req_1"]'), b64('["2026-10-01T12:00:00","req_1"]'),  # naive ts
           b64('["2026-10-01T12:00:00+00:00",5]'), b64('["2026-10-01T12:00:00+00:00","a b"]'),
           b64(json.dumps(["2026-10-01T12:00:00+00:00", "x" * 200])), "A" * 300]
    for c in bad:
        r = _feed(client, cursor=c)
        assert r.status_code == 422, c
        assert r.json()["error"]["code"] in ("invalid_cursor", "validation_error")


def test_limit_bounds(client, clock):
    _seed(client, clock, 3)
    for size in (0, 101, -1):
        assert _feed(client, page_size=size).status_code == 422
    assert _feed(client, page_size=1).status_code == 200 and _feed(client, page_size=100).status_code == 200
    cur = _feed(client, page_size=1).json()["next_cursor"]
    for size in (0, 101):
        assert _feed(client, page_size=size, cursor=cur).status_code == 422
    assert len(_feed(client, page_size=1, cursor=cur).json()["items"]) == 1


def test_mine_scope_and_filters_with_cursor(client, clock):
    _seed(client, clock, 4)
    r = client.get("/v1/requests", params={"page_size": 3}, headers=BUYER).json()
    r2 = client.get("/v1/requests", params={"page_size": 3, "cursor": r["next_cursor"]}, headers=BUYER).json()
    assert len(r["items"]) == 3 and len(r2["items"]) == 1 and r2["next_cursor"] is None
    assert _feed(client, kind="production_line").json()["items"] == []


@pytest.mark.parametrize("n", [0, 1])
def test_small_feeds(client, clock, n):
    _seed(client, clock, n)
    body = _feed(client, page_size=5).json()
    assert len(body["items"]) == n and body["next_cursor"] is None
