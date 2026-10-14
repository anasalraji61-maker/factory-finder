from conftest import SUP, post, uh

ADM = {"X-Admin-Token": "adm-secret", "X-User-Id": "admin"}


def test_admin_disabled_without_token_is_404(client):
    for path in ("/v1/admin/feed/posts", "/v1/admin/feed/comments", "/v1/admin/feed/reports"):
        r = client.get(path, headers=ADM)
        assert r.status_code == 404, path
    assert client.post("/v1/admin/feed/posts/post_x/hide", headers=ADM, json={"reason": "abc"}).status_code == 404
    assert client.post("/v1/admin/feed/posts/post_x/restore", headers=ADM).status_code == 404


def test_admin_requires_correct_token(make_client):
    c = make_client(admin_token="adm-secret")
    assert c.get("/v1/admin/feed/posts").status_code == 401
    assert c.get("/v1/admin/feed/posts", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert c.get("/v1/admin/feed/posts", headers={"X-Admin-Token": "adm-secret"}).status_code == 200
    # a user identity alone is not enough
    assert c.get("/v1/admin/feed/posts", headers=uh()).status_code == 401


def test_admin_hide_restore_post(make_client):
    c = make_client(admin_token="adm-secret", rate_posts=0, rate_reports=0, rate_likes=0)
    p = post(c)
    r = c.post(f"/v1/admin/feed/posts/{p['id']}/hide", headers=ADM, json={"reason": "misleading claims"})
    assert r.status_code == 200 and r.json()["status"] == "hidden"
    assert r.json()["hidden_reason"].startswith("admin:")
    assert c.get(f"/v1/feed/posts/{p['id']}", headers=uh()).status_code == 404
    listed = c.get("/v1/admin/feed/posts", headers=ADM).json()  # default: hidden
    assert [i["id"] for i in listed["items"]] == [p["id"]]
    assert listed["items"][0]["author_user_id"] and "report_count" in listed["items"][0]
    assert c.get("/v1/admin/feed/posts?status=published", headers=ADM).json()["items"] == []
    assert c.get("/v1/admin/feed/posts?status=all", headers=ADM).json()["items"]
    assert c.get("/v1/admin/feed/posts?status=bogus", headers=ADM).status_code == 422
    r = c.post(f"/v1/admin/feed/posts/{p['id']}/restore", headers=ADM)
    assert r.json()["status"] == "published" and r.json()["report_count"] == 0
    assert c.get(f"/v1/feed/posts/{p['id']}", headers=uh()).status_code == 200
    assert c.post("/v1/admin/feed/posts/post_nope/hide", headers=ADM, json={"reason": "abc"}).status_code == 404
    assert c.post(f"/v1/admin/feed/posts/{p['id']}/hide", headers=ADM, json={"reason": "x"}).status_code == 422


def test_restore_clears_reports_so_threshold_restarts(make_client):
    c = make_client(admin_token="adm-secret", report_hide_threshold=2, rate_posts=0, rate_reports=0)
    p = post(c)
    for u in ("r1", "r2"):
        c.post(f"/v1/feed/posts/{p['id']}/report", headers=uh(u), json={"reason": "spam", "details": "email a@b.com"})
    assert c.get(f"/v1/feed/posts/{p['id']}", headers=uh()).status_code == 404
    reps = c.get("/v1/admin/feed/reports", params={"target_id": p["id"]}, headers=ADM).json()
    assert len(reps["items"]) == 2 and "a@b.com" not in str(reps)  # details are redacted
    assert c.get("/v1/admin/feed/reports?target_type=comment", headers=ADM).json()["items"] == []
    c.post(f"/v1/admin/feed/posts/{p['id']}/restore", headers=ADM)
    c.post(f"/v1/feed/posts/{p['id']}/report", headers=uh("r1"), json={"reason": "spam"})
    assert c.get(f"/v1/feed/posts/{p['id']}", headers=uh()).status_code == 200  # 1 < threshold again


def test_admin_comment_moderation(make_client):
    c = make_client(admin_token="adm-secret", rate_posts=0, rate_comments=0)
    p = post(c)
    cm = c.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh("w"), json={"body": "hi"}).json()
    r = c.post(f"/v1/admin/feed/comments/{cm['id']}/hide", headers=ADM, json={"reason": "offensive"})
    assert r.json()["status"] == "hidden"
    assert c.get(f"/v1/feed/posts/{p['id']}/comments", headers=uh()).json()["items"] == []
    assert c.get(f"/v1/feed/posts/{p['id']}", headers=uh()).json()["comment_count"] == 0
    assert [i["id"] for i in c.get("/v1/admin/feed/comments", params={"post_id": p["id"]}, headers=ADM).json()["items"]] == [cm["id"]]
    c.post(f"/v1/admin/feed/comments/{cm['id']}/restore", headers=ADM)
    assert c.get(f"/v1/feed/posts/{p['id']}", headers=uh()).json()["comment_count"] == 1
    assert c.post("/v1/admin/feed/comments/cmt_nope/hide", headers=ADM, json={"reason": "abc"}).status_code == 404


def test_admin_pagination(make_client):
    c = make_client(admin_token="adm-secret", rate_posts=0)
    made = [post(c, f"p{i}")["id"] for i in range(5)]
    seen, cur = [], None
    while True:
        r = c.get("/v1/admin/feed/posts", params={"status": "all", "limit": 2, **({"cursor": cur} if cur else {})}, headers=ADM).json()
        seen += [i["id"] for i in r["items"]]
        cur = r["next_cursor"]
        if not cur:
            break
    assert seen == made[::-1]
    assert SUP
