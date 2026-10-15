"""QA round 3 edge cases: empty, duplicate, oversized, unicode."""

import pytest
from conftest import MEDIA, SUP, post, sh, uh

AR = "مكائن خياطة مستعملة بسعر ممتاز في البصرة"


def test_empty_feeds_return_empty_pages(client):
    for path in ("/v1/feed/home", "/v1/feed/trending", "/v1/feed/following", f"/v1/feed/suppliers/{SUP}/posts"):
        r = client.get(path, headers=uh())
        assert r.status_code == 200, path
        j = r.json()
        assert j["items"] == [] and not j.get("next_cursor")


def test_unicode_body_roundtrip_arabic_and_emoji(client):
    body = AR + " 🏭🇮🇶 ١٢٣ ‫RTL"
    p = post(client, body.replace("‫", ""))
    assert client.get(f"/v1/feed/posts/{p['id']}", headers=uh()).json()["body"] == body.replace("‫", "")


def test_emoji_counted_as_characters_not_bytes(client):
    assert post(client, "🏭" * 2000)["body"] == "🏭" * 2000
    r = client.post("/v1/feed/posts", headers=sh(), json={"body": "🏭" * 2001})
    assert r.status_code == 422


@pytest.mark.parametrize("ws", [" ", "　", " ", " \n\t "])
def test_unicode_whitespace_only_body_rejected(client, ws):
    assert client.post("/v1/feed/posts", headers=sh(), json={"body": ws}).status_code == 422
    p = post(client, "x")
    assert client.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh(), json={"body": ws}).status_code == 422


def test_arabic_tags_and_duplicate_tags_deduped(client):
    p = post(client, "x", tags=["#خياطة", "خياطة", "Machines", "machines"])
    assert p["tags"] == ["خياطة", "machines"]


def test_duplicate_media_urls_do_not_crash(client):
    r = client.post("/v1/feed/posts", headers=sh(), json={"body": "x", "media": [MEDIA, MEDIA]})
    assert r.status_code in (201, 422)
    if r.status_code == 201:
        assert r.json()["media"].count(MEDIA) == 1


def test_double_like_and_double_follow_idempotent(client):
    p = post(client, "x")
    for _ in range(2):
        assert client.put(f"/v1/feed/posts/{p['id']}/like", headers=uh("b1")).status_code in (200, 204)
    assert client.get(f"/v1/feed/posts/{p['id']}", headers=uh("b1")).json()["like_count"] == 1
    for _ in range(2):
        assert client.post("/v1/feed/suppliers/sup_beta/follow", headers=uh("b1")).status_code in (200, 201, 204)
    for _ in range(2):
        assert client.delete(f"/v1/feed/posts/{p['id']}/like", headers=uh("b1")).status_code in (200, 204)
    assert client.get(f"/v1/feed/posts/{p['id']}", headers=uh("b1")).json()["like_count"] == 0


@pytest.mark.parametrize("cursor", ["", "!!!", "a" * 5000, "eyJ4IjoxfQ", "ال"])
def test_garbage_cursor_is_a_clean_4xx(client, cursor):
    post(client, "x")
    r = client.get("/v1/feed/home", headers=uh(), params={"cursor": cursor})
    assert r.status_code in (200, 400, 422), r.text
    assert r.status_code < 500


@pytest.mark.parametrize("limit", ["0", "-1", "abc", "1000000"])
def test_bad_limit_is_clean(client, limit):
    r = client.get("/v1/feed/trending", headers=uh(), params={"limit": limit})
    assert r.status_code in (200, 422)
    if r.status_code == 200:
        assert len(r.json()["items"]) <= 100


def test_oversized_json_body_rejected_not_500(client):
    h = {**sh(), "Content-Type": "application/json"}
    r = client.post("/v1/feed/posts", headers=h, content=b'{"body":"' + b"x" * 5_000_000 + b'"}')
    assert r.status_code in (413, 422)


def test_invalid_utf8_and_non_json_body_clean(client):
    h = {**sh(), "Content-Type": "application/json"}
    assert client.post("/v1/feed/posts", headers=h, content=b'{"body":"\xff\xfe"}').status_code in (400, 422)
    assert client.post("/v1/feed/posts", headers=h, content=b"not json").status_code == 422


def test_unicode_user_and_supplier_ids_rejected(client):
    r = client.get("/v1/feed/home", headers={"X-User-Id": "مستخدم".encode()})
    assert r.status_code in (400, 401, 422)
    r = client.post("/v1/feed/posts", headers={"X-User-Id": b"u1", "X-Supplier-Id": "sup_مورد".encode()}, json={"body": "x"})
    assert r.status_code == 403


def test_comment_on_missing_and_deleted_post(client):
    assert client.post("/v1/feed/posts/post_nope/comments", headers=uh(), json={"body": "hi"}).status_code == 404
    p = post(client, "x")
    assert client.delete(f"/v1/feed/posts/{p['id']}", headers=sh()).status_code == 204
    assert client.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh(), json={"body": "hi"}).status_code == 404
    assert client.delete(f"/v1/feed/posts/{p['id']}", headers=sh()).status_code in (204, 404)
