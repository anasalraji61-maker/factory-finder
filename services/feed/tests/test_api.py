import pytest
from conftest import MEDIA, SUP, SUP2, post, sh, uh

# ---------------------------------------------------------------- posts


def test_create_and_get_post(client):
    p = post(client, "  Fresh stock #1  ", media=[MEDIA], tags=["#CNC", "cnc", "Machines"], listing_ref="lst_1")
    assert p["id"].startswith("post_") and p["supplier_id"] == SUP
    assert p["body"] == "Fresh stock #1" and p["tags"] == ["cnc", "machines"]
    assert p["media"] == [MEDIA] and p["listing_ref"] == "lst_1"
    assert (p["like_count"], p["comment_count"], p["viewer_liked"]) == (0, 0, False)
    assert p["created_at"].endswith("Z")
    got = client.get(f"/v1/feed/posts/{p['id']}", headers=uh())
    assert got.status_code == 200 and got.json() == p
    assert client.get("/v1/feed/posts/post_nope", headers=uh()).status_code == 404


def test_post_requires_verified_supplier_and_user(client):
    r = client.post("/v1/feed/posts", headers=uh(), json={"body": "hi"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "supplier_required"
    r = client.post("/v1/feed/posts", headers=uh(supplier="not-a-supplier-id"), json={"body": "hi"})
    assert r.status_code == 403
    assert client.post("/v1/feed/posts", json={"body": "hi"}).status_code == 401
    assert client.get("/v1/feed/home").status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"body": ""},
        {"body": "   "},
        {"body": "x" * 2001},
        {"body": "ok", "media": [MEDIA] * 6},
        {"body": "ok", "tags": ["a", "b", "c", "d", "e", "f"]},
        {"body": "ok", "tags": ["bad tag"]},
        {"body": "ok", "listing_ref": "has space"},
        {"body": "ok", "extra": 1},
        {"body": "bad\x00char"},
    ],
)
def test_post_validation(client, payload):
    r = client.post("/v1/feed/posts", headers=sh(), json=payload)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_post_max_length_ok(client):
    assert post(client, "x" * 2000)["body"] == "x" * 2000


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/v1/media/files/" + "a" * 32 + ".png",
        "/v1/media/files/../../x.png",
        "/v1/media/files/" + "a" * 32 + ".png?w=200",
        "/v1/media/files/" + "a" * 32 + ".gif",
        "/v1/media/images/" + "a" * 32,
        "/static/a.png",
        "http://localhost/v1/media/files/" + "a" * 32 + ".png",  # no media_base_url configured
        "javascript:alert(1)",
    ],
)
def test_media_must_be_media_service_paths(client, url):
    r = client.post("/v1/feed/posts", headers=sh(), json={"body": "ok", "media": [url]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_media"


def test_media_absolute_url_only_for_configured_base(make_client):
    c = make_client(media_base_url="https://api.example.com/", rate_posts=0)
    good = "https://api.example.com/v1/media/files/" + "b" * 32 + ".webp"
    assert post(c, media=[good, good])["media"] == [good]
    for bad in (
        "https://api.example.com.evil.io/v1/media/files/" + "b" * 32 + ".webp",
        "https://other.example.com/v1/media/files/" + "b" * 32 + ".webp",
    ):
        assert c.post("/v1/feed/posts", headers=sh(), json={"body": "x", "media": [bad]}).status_code == 422


def test_delete_post_owner_only_cascades(client):
    p = post(client)
    c = client.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh("u1"), json={"body": "nice"}).json()
    client.put(f"/v1/feed/posts/{p['id']}/like", headers=uh("u1"))
    assert client.delete(f"/v1/feed/posts/{p['id']}", headers=uh("u1")).status_code == 403
    assert client.delete(f"/v1/feed/posts/{p['id']}", headers=sh(SUP2)).status_code == 403
    assert client.delete(f"/v1/feed/posts/{p['id']}", headers=sh(SUP)).status_code == 204
    assert client.get(f"/v1/feed/posts/{p['id']}", headers=uh()).status_code == 404
    assert client.delete(f"/v1/feed/posts/{p['id']}", headers=sh(SUP)).status_code == 404
    assert client.delete(f"/v1/feed/comments/{c['id']}", headers=uh("u1")).status_code == 404


def test_post_cap_per_supplier(make_client):
    c = make_client(max_posts_per_supplier=2, rate_posts=0)
    post(c)
    post(c)
    r = c.post("/v1/feed/posts", headers=sh(), json={"body": "third"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "post_limit_reached"
    post(c, supplier=SUP2)  # other suppliers unaffected


# ---------------------------------------------------------------- screening


@pytest.mark.parametrize(
    "text",
    [
        "Call me on +964 770 123 4567",
        "write to sales@factory.com",
        "visit www.factory-shop.com now",
        "see https://example.org/page",
        "ping me on whatsapp",
        "تواصل معنا على واتساب",
        "رقمي ٠٧٧٠١٢٣٤٥٦٧٨",
        "selling AK-47 rifles cheap",
    ],
)
def test_screening_rejects_contacts_and_banned_goods(client, text):
    r = client.post("/v1/feed/posts", headers=sh(), json={"body": text})
    e = r.json()["error"]
    assert r.status_code == 422 and e["code"] == "content_rejected"
    assert e["details"]["reasons"]
    blob = str(e)
    assert "factory.com" not in blob and "770" not in blob  # never echoes the match


def test_screening_applies_to_tags_and_comments(client):
    assert client.post("/v1/feed/posts", headers=sh(), json={"body": "ok", "tags": ["whatsapp"]}).status_code == 422
    p = post(client)
    r = client.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh(), json={"body": "email me a@b.com"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "content_rejected"
    assert client.get(f"/v1/feed/posts/{p['id']}", headers=uh()).json()["comment_count"] == 0


def test_clean_text_passes(client):
    post(client, "Prices from 12.50 USD per unit, MOQ 100 pieces. مصنع كراسي بلاستيك")


# ---------------------------------------------------------------- follow + feeds


def ids(page):
    return [i["id"] for i in page["items"]]


def test_follow_unfollow_idempotent(client):
    h = uh("u1")
    r = client.post(f"/v1/feed/suppliers/{SUP}/follow", headers=h)
    assert r.status_code == 200 and r.json() == {"supplier_id": SUP, "following": True, "follower_count": 1}
    assert client.post(f"/v1/feed/suppliers/{SUP}/follow", headers=h).json()["follower_count"] == 1
    assert client.post(f"/v1/feed/suppliers/{SUP}/follow", headers=uh("u2")).json()["follower_count"] == 2
    assert [i["supplier_id"] for i in client.get("/v1/feed/following", headers=h).json()["items"]] == [SUP]
    r = client.delete(f"/v1/feed/suppliers/{SUP}/follow", headers=h)
    assert r.json() == {"supplier_id": SUP, "following": False, "follower_count": 1}
    assert client.delete(f"/v1/feed/suppliers/{SUP}/follow", headers=h).json()["following"] is False
    assert client.get("/v1/feed/following", headers=h).json()["items"] == []


def test_follow_validation(client):
    assert client.post("/v1/feed/suppliers/bad id/follow", headers=uh()).status_code == 422
    assert client.post("/v1/feed/suppliers/notsup/follow", headers=uh()).status_code == 422
    r = client.post(f"/v1/feed/suppliers/{SUP}/follow", headers=sh(SUP))
    assert r.status_code == 422 and r.json()["error"]["code"] == "cannot_follow_self"


def test_follow_cap(make_client):
    c = make_client(max_follows_per_user=2, rate_follows=0)
    for s in ("sup_a", "sup_b"):
        assert c.post(f"/v1/feed/suppliers/{s}/follow", headers=uh()).status_code == 200
    assert c.post("/v1/feed/suppliers/sup_a/follow", headers=uh()).status_code == 200  # idempotent at cap
    r = c.post("/v1/feed/suppliers/sup_c/follow", headers=uh())
    assert r.status_code == 409 and r.json()["error"]["code"] == "follow_limit_reached"


def test_home_follows_newest_first_then_fallback_to_trending(client):
    a1, a2 = post(client, "a1", SUP), post(client, "a2", SUP)
    b1 = post(client, "b1", SUP2)
    # follows nobody -> trending
    home = client.get("/v1/feed/home", headers=uh("u1")).json()
    assert home["source"] == "trending" and set(ids(home)) == {a1["id"], a2["id"], b1["id"]}
    client.post(f"/v1/feed/suppliers/{SUP}/follow", headers=uh("u1"))
    home = client.get("/v1/feed/home", headers=uh("u1")).json()
    assert home["source"] == "following" and ids(home) == [a2["id"], a1["id"]]
    client.post(f"/v1/feed/suppliers/{SUP2}/follow", headers=uh("u1"))
    assert ids(client.get("/v1/feed/home", headers=uh("u1")).json()) == [b1["id"], a2["id"], a1["id"]]
    # a follower of a supplier with no posts falls back as well
    client.post("/v1/feed/suppliers/sup_empty/follow", headers=uh("u9"))
    assert client.get("/v1/feed/home", headers=uh("u9")).json()["source"] == "trending"


def test_home_pagination_keyset_no_dupes_even_with_new_posts(client):
    client.post(f"/v1/feed/suppliers/{SUP}/follow", headers=uh("u1"))
    made = [post(client, f"p{i}")["id"] for i in range(7)]
    p1 = client.get("/v1/feed/home?limit=3", headers=uh("u1")).json()
    assert ids(p1) == made[::-1][:3] and p1["next_cursor"]
    post(client, "brand new")  # arrives between pages: must not shift the window
    p2 = client.get(f"/v1/feed/home?limit=3&cursor={p1['next_cursor']}", headers=uh("u1")).json()
    assert ids(p2) == made[::-1][3:6]
    p3 = client.get(f"/v1/feed/home?limit=3&cursor={p2['next_cursor']}", headers=uh("u1")).json()
    assert ids(p3) == made[::-1][6:] and p3["next_cursor"] is None and p3["source"] == "following"


def test_trending_orders_by_engagement_and_pages(client, clock):
    ps = [post(client, f"t{i}")["id"] for i in range(5)]
    client.put(f"/v1/feed/posts/{ps[1]}/like", headers=uh("a"))
    client.put(f"/v1/feed/posts/{ps[1]}/like", headers=uh("b"))
    client.post(f"/v1/feed/posts/{ps[3]}/comments", headers=uh("a"), json={"body": "hello"})  # +2
    client.put(f"/v1/feed/posts/{ps[0]}/like", headers=uh("a"))
    seen, cursor = [], None
    while True:
        url = "/v1/feed/trending?limit=2" + (f"&cursor={cursor}" if cursor else "")
        page = client.get(url).json()  # public: no identity needed
        seen += ids(page)
        cursor = page["next_cursor"]
        if not cursor:
            break
    # score 2: ps[1] (newest-first tie-break after ps[3]); ps[3]=2; ps[0]=1; then zeros newest first
    assert seen == [ps[3], ps[1], ps[0], ps[4], ps[2]]
    clock.advance(days=15)  # outside the trending window
    assert client.get("/v1/feed/trending").json()["items"] == []


def test_trending_excludes_hidden_and_marks_viewer_liked(client):
    p = post(client)
    client.put(f"/v1/feed/posts/{p['id']}/like", headers=uh("a"))
    assert client.get("/v1/feed/trending", headers=uh("a")).json()["items"][0]["viewer_liked"] is True
    assert client.get("/v1/feed/trending", headers=uh("b")).json()["items"][0]["viewer_liked"] is False
    assert client.get("/v1/feed/trending").json()["items"][0]["viewer_liked"] is False


def test_supplier_posts_listing(client):
    a = post(client, "a", SUP)
    post(client, "b", SUP2)
    page = client.get(f"/v1/feed/suppliers/{SUP}/posts", headers=uh()).json()
    assert ids(page) == [a["id"]] and page["next_cursor"] is None


@pytest.mark.parametrize("cursor", ["garbage", "e30", "a" * 400, "eyJrIjoieCJ9", "%%%"])
def test_invalid_cursor_is_422(client, cursor):
    for path in ("/v1/feed/home", "/v1/feed/trending", f"/v1/feed/suppliers/{SUP}/posts", "/v1/feed/following"):
        r = client.get(path, params={"cursor": cursor}, headers=uh())
        assert r.status_code == 422, (path, r.text)


def test_cursor_kind_mismatch_rejected(client):
    post(client, "a")
    post(client, "b")
    tr = client.get("/v1/feed/trending?limit=1").json()["next_cursor"]
    assert tr
    assert client.get("/v1/feed/suppliers/sup_x/posts", params={"cursor": tr}, headers=uh()).status_code == 422


def test_limit_caps(client):
    assert client.get("/v1/feed/trending?limit=0").status_code == 422
    assert client.get("/v1/feed/trending?limit=51").status_code == 422
    for i in range(3):
        post(client, f"p{i}")
    assert len(client.get("/v1/feed/trending?limit=50").json()["items"]) == 3


# ---------------------------------------------------------------- likes


def test_like_unlike_idempotent(client):
    p = post(client)
    url = f"/v1/feed/posts/{p['id']}/like"
    assert client.put(url, headers=uh("a")).json() == {"post_id": p["id"], "liked": True, "like_count": 1}
    assert client.put(url, headers=uh("a")).json()["like_count"] == 1
    assert client.put(url, headers=uh("b")).json()["like_count"] == 2
    assert client.delete(url, headers=uh("a")).json() == {"post_id": p["id"], "liked": False, "like_count": 1}
    assert client.delete(url, headers=uh("a")).json()["like_count"] == 1
    assert client.get(f"/v1/feed/posts/{p['id']}", headers=uh("b")).json()["viewer_liked"] is True
    assert client.put("/v1/feed/posts/post_nope/like", headers=uh()).status_code == 404
    assert client.delete("/v1/feed/posts/post_nope/like", headers=uh()).status_code == 404


# ---------------------------------------------------------------- comments


def test_comments_flow(client):
    p = post(client)
    base = f"/v1/feed/posts/{p['id']}/comments"
    made = []
    for i in range(5):
        r = client.post(base, headers=uh(f"u{i}"), json={"body": f"c{i}"})
        assert r.status_code == 201 and r.json()["post_id"] == p["id"]
        made.append(r.json()["id"])
    assert client.get(f"/v1/feed/posts/{p['id']}", headers=uh()).json()["comment_count"] == 5
    page = client.get(base + "?limit=2", headers=uh()).json()  # oldest first
    assert ids(page) == made[:2]
    page2 = client.get(base, params={"limit": 10, "cursor": page["next_cursor"]}, headers=uh()).json()
    assert ids(page2) == made[2:] and page2["next_cursor"] is None
    # delete: author, and the post's supplier; strangers cannot
    assert client.delete(f"/v1/feed/comments/{made[0]}", headers=uh("stranger")).status_code == 403
    assert client.delete(f"/v1/feed/comments/{made[0]}", headers=uh("u0")).status_code == 204
    assert client.delete(f"/v1/feed/comments/{made[1]}", headers=sh(SUP)).status_code == 204
    assert client.delete(f"/v1/feed/comments/{made[2]}", headers=sh(SUP2)).status_code == 403
    assert client.get(f"/v1/feed/posts/{p['id']}", headers=uh()).json()["comment_count"] == 3


@pytest.mark.parametrize("body", ["", "  ", "x" * 501, "bad\x01"])
def test_comment_validation(client, body):
    p = post(client)
    r = client.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh(), json={"body": body})
    assert r.status_code == 422


def test_comment_max_ok_and_missing_post(client):
    p = post(client)
    assert client.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh(), json={"body": "y" * 500}).status_code == 201
    assert client.post("/v1/feed/posts/post_nope/comments", headers=uh(), json={"body": "hi"}).status_code == 404
    assert client.get("/v1/feed/posts/post_nope/comments", headers=uh()).status_code == 404


def test_comment_cap_per_post(make_client):
    c = make_client(max_comments_per_post=2, rate_comments=0, rate_posts=0)
    p = post(c)
    url = f"/v1/feed/posts/{p['id']}/comments"
    for _ in range(2):
        assert c.post(url, headers=uh(), json={"body": "hi"}).status_code == 201
    r = c.post(url, headers=uh(), json={"body": "hi"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "comment_limit_reached"


# ---------------------------------------------------------------- reports


def rep(client, kind, tid, user, reason="spam", **kw):
    return client.post(f"/v1/feed/{kind}s/{tid}/report", headers=uh(user), json={"reason": reason, **kw})


def test_post_report_threshold_hides(make_client):
    c = make_client(report_hide_threshold=3, rate_posts=0, rate_reports=0)
    p = post(c)
    for u in ("r1", "r2"):
        r = rep(c, "post", p["id"], u)
        assert r.status_code == 202 and r.json() == {"status": "received"}
    assert rep(c, "post", p["id"], "r2").status_code == 202  # repeated: same answer, not counted twice
    assert c.get(f"/v1/feed/posts/{p['id']}", headers=uh()).status_code == 200
    assert rep(c, "post", p["id"], "r3", details="mail me x@y.com or +96477012345678").status_code == 202
    assert c.get(f"/v1/feed/posts/{p['id']}", headers=uh()).status_code == 404
    assert c.get("/v1/feed/trending").json()["items"] == []
    assert c.get(f"/v1/feed/suppliers/{SUP}/posts", headers=uh()).json()["items"] == []
    assert c.put(f"/v1/feed/posts/{p['id']}/like", headers=uh()).status_code == 404
    assert rep(c, "post", p["id"], "r4").status_code == 404


def test_report_rules(client):
    p = post(client)
    assert client.post(f"/v1/feed/posts/{p['id']}/report", headers=sh(SUP), json={"reason": "spam"}).status_code == 422
    assert rep(client, "post", p["id"], "u", reason="nonsense").status_code == 422
    assert rep(client, "post", "post_nope", "u").status_code == 404
    assert client.post(f"/v1/feed/posts/{p['id']}/report", json={"reason": "spam"}).status_code == 401
    c = client.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh("w"), json={"body": "hi"}).json()
    assert rep(client, "comment", c["id"], "w").status_code == 422  # own comment


def test_comment_report_threshold_hides_and_recounts(make_client):
    c = make_client(report_hide_threshold=2, rate_posts=0, rate_comments=0, rate_reports=0)
    p = post(c)
    cm = c.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh("w"), json={"body": "hi"}).json()
    rep(c, "comment", cm["id"], "r1")
    rep(c, "comment", cm["id"], "r2")
    assert c.get(f"/v1/feed/posts/{p['id']}/comments", headers=uh()).json()["items"] == []
    assert c.get(f"/v1/feed/posts/{p['id']}", headers=uh()).json()["comment_count"] == 0


# ---------------------------------------------------------------- rate limits


def test_rate_limit_posts_per_user_window(make_client, clock):
    c = make_client(rate_posts=2, rate_window_seconds=60)
    post(c)
    post(c)
    r = c.post("/v1/feed/posts", headers=sh(), json={"body": "third"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1
    # another user is unaffected; the window slides
    post(c, supplier=SUP2)
    clock.advance(seconds=61)
    post(c)


def test_rejected_screening_still_counts_against_rate_limit(make_client):
    c = make_client(rate_posts=2, rate_window_seconds=3600)
    for _ in range(2):
        assert c.post("/v1/feed/posts", headers=sh(), json={"body": "call +964 770 123 4567"}).status_code == 422
    assert c.post("/v1/feed/posts", headers=sh(), json={"body": "fine"}).status_code == 429


@pytest.mark.parametrize(
    ("kw", "call"),
    [
        ("rate_likes", lambda c, p: c.put(f"/v1/feed/posts/{p}/like", headers=uh("z"))),
        ("rate_comments", lambda c, p: c.post(f"/v1/feed/posts/{p}/comments", headers=uh("z"), json={"body": "x"})),
        ("rate_follows", lambda c, p: c.post(f"/v1/feed/suppliers/{SUP}/follow", headers=uh("z"))),
        ("rate_reports", lambda c, p: c.post(f"/v1/feed/posts/{p}/report", headers=uh("z"), json={"reason": "spam"})),
    ],
)
def test_other_actions_rate_limited(make_client, kw, call):
    c = make_client(rate_posts=0, **{kw: 1})
    p = post(c)["id"]
    assert call(c, p).status_code in (200, 201, 202)
    assert call(c, p).status_code == 429


def test_reads_are_not_rate_limited(make_client):
    c = make_client(rate_posts=0, rate_likes=1)
    for _ in range(5):
        assert c.get("/v1/feed/trending").status_code == 200
