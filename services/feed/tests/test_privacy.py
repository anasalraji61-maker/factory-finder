from conftest import SUP, SUP2, sh, uh

TOK = {"X-Internal-Token": "s3cret"}


def hh(h):
    return {**h, **TOK}


def test_internal_routes_404_for_non_internal(make_client):
    c = make_client(internal_token="s3cret")
    assert c.post("/v1/internal/users/u/export").status_code == 404
    assert c.delete("/v1/internal/users/u/data", headers={"X-Internal-Token": "bad"}).status_code == 404


def test_export_erase_marks_comments_and_cleans_counters(make_client):
    c = make_client(internal_token="s3cret", rate_posts=0, rate_comments=0, rate_likes=0, rate_follows=0)
    other = c.post("/v1/feed/posts", headers=hh(sh(SUP2)), json={"body": "someone else"}).json()
    own = c.post("/v1/feed/posts", headers=hh(sh(SUP, user="leaver")), json={"body": "my post"}).json()
    assert c.put(f"/v1/feed/posts/{other['id']}/like", headers=hh(uh("leaver"))).status_code in (200, 201)
    assert c.post(f"/v1/feed/posts/{other['id']}/comments", headers=hh(uh("leaver")), json={"body": "nice"}).status_code == 201
    assert c.post(f"/v1/feed/posts/{other['id']}/comments", headers=hh(uh("stay")), json={"body": "keep me"}).status_code == 201
    assert c.post(f"/v1/feed/suppliers/{SUP2}/follow", headers=hh(uh("leaver"))).status_code in (200, 201)
    exp = c.post("/v1/internal/users/leaver/export", headers=TOK).json()
    assert [p["id"] for p in exp["data"]["posts"]] == [own["id"]] and len(exp["data"]["comments"]) == 1
    d = c.delete("/v1/internal/users/leaver/data", headers=TOK).json()
    assert d["status"] == "done" and d["counts"]["posts_deleted"] == 1 and d["counts"]["comments_marked_deleted"] == 1
    again = c.delete("/v1/internal/users/leaver/data", headers=TOK).json()
    assert sum(again["counts"].values()) == 0
    assert c.get(f"/v1/feed/posts/{own['id']}", headers=hh(uh("stay"))).status_code == 404
    got = c.get(f"/v1/feed/posts/{other['id']}", headers=hh(uh("stay"))).json()
    assert (got["like_count"], got["comment_count"]) == (0, 1)  # counters follow the erasure
    texts = [x["body"] for x in c.get(f"/v1/feed/posts/{other['id']}/comments", headers=hh(uh("stay"))).json()["items"]]
    assert texts == ["keep me"]
    assert "leaver" not in str(c.post("/v1/internal/users/leaver/export", headers=TOK).json()["data"]["comments"])
