"""QA5: spam rate, hidden-content visibility on every read path, tag/mention injection, confusables."""

import pytest
from conftest import SUP, post, sh, uh

ADMIN = {"X-Admin-Token": "adm", "X-User-Id": "admin"}


def test_spam_rate_limit_and_whitespace_variants_still_duplicate(make_client):
    c = make_client(rate_posts=3, antispam_author_history=10, antispam_min_tokens=3)
    codes = [c.post("/v1/feed/posts", headers=sh(), json={"body": f"Fresh stock batch number {i} of widgets"}).status_code for i in range(5)]
    assert codes[:3] == [201, 201, 201] and codes[3:] == [429, 429]
    c2 = make_client(rate_posts=0, antispam_author_history=10, antispam_min_tokens=3)
    assert c2.post("/v1/feed/posts", headers=sh(), json={"body": "Cheap steel pipes for sale today"}).status_code == 201
    for variant in ("CHEAP  steel   pipes for sale today!!!", "Ｃheap steel pipes for sale today", "cheap​ steel pipes, for sale today"):
        r = c2.post("/v1/feed/posts", headers=sh(), json={"body": variant})
        assert r.status_code == 409, (variant, r.text)


def test_fresh_accounts_cannot_bypass_rate_by_supplier_header_switch(make_client):
    c = make_client(rate_posts=2)
    ok = 0
    for i in range(6):
        r = c.post("/v1/feed/posts", headers=uh("same_user", "sup_acme"), json={"body": f"unique offer number {i} for you"})
        ok += r.status_code == 201
    assert ok == 2


def test_hidden_post_invisible_on_every_read_path(make_client):
    client = make_client(admin_token="adm", rate_posts=0, rate_comments=0, rate_likes=0, rate_follows=0, rate_reports=0)
    p = post(client, "Hidden candidate steel sheets")
    pid = p["id"]
    client.post(f"/v1/feed/follow/{SUP}", headers=uh("fan"))
    client.post(f"/v1/feed/posts/{pid}/comments", headers=uh("fan"), json={"body": "nice"})
    r = client.post(f"/v1/admin/feed/posts/{pid}/hide", headers=ADMIN, json={"reason": "spam test"})
    if r.status_code in (401, 403, 404):
        pytest.skip(f"admin route differs: {r.status_code}")
    for path in (f"/v1/feed/posts/{pid}", f"/v1/feed/posts/{pid}/comments", f"/v1/feed/suppliers/{SUP}/posts", "/v1/feed/home", "/v1/feed/trending"):
        for h in (uh("fan"), sh()):
            resp = client.get(path, headers=h)
            assert pid not in resp.text, (path, resp.text[:200])
    assert client.put(f"/v1/feed/posts/{pid}/like", headers=uh("fan")).status_code == 404
    assert client.post(f"/v1/feed/posts/{pid}/comments", headers=uh("fan"), json={"body": "still here?"}).status_code == 404
    assert client.post(f"/v1/feed/posts/{pid}/report", headers=uh("fan2"), json={"reason": "spam"}).status_code in (404, 409)


@pytest.mark.parametrize("tag", ["сnc", "c​nc", "ｃｎｃ", "a b", "<script>", "x" * 31, "#", "##x", "@admin", "ab‮cd"])
def test_tag_injection_and_confusables(client, tag):
    r = client.post("/v1/feed/posts", headers=sh(), json={"body": "Tagged machine offer", "tags": [tag]})
    if r.status_code == 201:
        got = r.json()["tags"]
        # whatever is accepted must be safe: no bidi/zero-width/format chars, NFKC-stable, no markup
        import unicodedata

        for t in got:
            assert unicodedata.normalize("NFKC", t) == t, got
            assert all(unicodedata.category(ch)[0] in "LNP" or ch in "_-" for ch in t), got
            assert not any(unicodedata.category(ch) == "Cf" for ch in t)
            assert "<" not in t and "@" not in t
    else:
        assert r.status_code == 422


def test_mention_and_hashtag_in_body_not_expanded_or_crashing(client):
    r = client.post("/v1/feed/posts", headers=sh(), json={"body": "Great deal @everyone contact me"})
    assert r.status_code == 422  # social handles are screened
    p = post(client, "Great deal #cnc #cnc #cnc offer of machines")
    assert p["tags"] == []  # hashtags in the body are never auto-promoted to tags


def test_mixed_script_tag_rejected(client):
    r = client.post("/v1/feed/posts", headers=sh(), json={"body": "Tagged machine offer", "tags": ["с" + "nc"]})
    assert r.status_code == 422
