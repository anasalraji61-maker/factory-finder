"""security-review-2026-10-d items 3 (report-abuse auto-hide) and 4 (evidence survives deletion)."""

from conftest import SUP, post, sh, uh

ADM = {"X-Admin-Token": "adm-secret"}
REP = {"reason": "spam"}


def _report(c, pid, user):
    return c.post(f"/v1/feed/posts/{pid}/report", headers=uh(user), json=REP)


def _touch(c, user):  # any write registers the account's first-seen time
    p = post(c, supplier="sup_other")
    assert c.put(f"/v1/feed/posts/{p['id']}/like", headers=uh(user)).status_code == 200


def test_new_accounts_cannot_auto_hide(make_client, clock):
    c = make_client(admin_token="adm-secret", report_hide_threshold=2, report_min_account_age_seconds=3600,
                    rate_posts=0, rate_likes=0, rate_reports=0)
    pid = post(c)["id"]
    for u in ("r1", "r2"):
        assert _report(c, pid, u).status_code == 202
    assert c.get(f"/v1/feed/posts/{pid}").status_code == 200  # visible, reports stored
    items = c.get("/v1/admin/feed/posts", params={"status": "published"}, headers=ADM).json()["items"]
    assert [i["report_count"] for i in items if i["id"] == pid] == [2]
    clock.advance(seconds=3601)
    _touch(c, "r3")  # fresh account does not count
    assert _report(c, pid, "r3").status_code == 202
    assert c.get(f"/v1/feed/posts/{pid}").status_code == 404  # r1 + r2 are now aged: threshold reached


def test_report_evidence_survives_post_delete(make_client):
    c = make_client(admin_token="adm-secret", report_hide_threshold=5, rate_posts=0, rate_comments=0, rate_reports=0)
    p = post(c)
    cm = c.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh("u1"), json={"body": "hello"}).json()
    assert _report(c, p["id"], "r1").status_code == 202
    assert c.post(f"/v1/feed/comments/{cm['id']}/report", headers=uh("r2"), json=REP).status_code == 202
    assert c.delete(f"/v1/feed/posts/{p['id']}", headers=sh(SUP)).status_code == 204
    got = c.get("/v1/admin/feed/reports", headers=ADM).json()["items"]
    assert {(r["target_type"], r["reporter_id"]) for r in got} == {("post", "r1"), ("comment", "r2")}


def test_report_evidence_survives_comment_delete(make_client):
    c = make_client(admin_token="adm-secret", report_hide_threshold=5, rate_posts=0, rate_comments=0, rate_reports=0)
    p = post(c)
    cm = c.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh("u1"), json={"body": "hello"}).json()
    assert c.post(f"/v1/feed/comments/{cm['id']}/report", headers=uh("r2"), json=REP).status_code == 202
    assert c.delete(f"/v1/feed/comments/{cm['id']}", headers=uh("u1")).status_code == 204
    assert len(c.get("/v1/admin/feed/reports", params={"target_type": "comment"}, headers=ADM).json()["items"]) == 1
