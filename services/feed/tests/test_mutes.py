"""Per-viewer supplier mutes: cap, idempotency, filtering across pagination, unmute, isolation."""

from conftest import SUP, SUP2, post, sh, uh

M = "/v1/feed/mutes"


def ids(r):
    assert r.status_code == 200, r.text
    return [i["id"] for i in r.json()["items"]]


def walk(client, url, headers, limit=3):
    out, cursor = [], None
    while True:
        r = client.get(url, headers=headers, params={"limit": limit, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text
        out += [i["id"] for i in r.json()["items"]]
        cursor = r.json()["next_cursor"]
        if not cursor:
            return out


def test_idempotent_put_delete_and_list(client):
    h = uh("viewer")
    for _ in range(2):
        r = client.put(f"{M}/{SUP}", headers=h)
        assert r.status_code == 200 and r.json() == {"supplier_id": SUP, "muted": True}
    assert [i["supplier_id"] for i in client.get(M, headers=h).json()["items"]] == [SUP]
    for _ in range(2):
        assert client.delete(f"{M}/{SUP}", headers=h).json() == {"supplier_id": SUP, "muted": False}
    assert client.get(M, headers=h).json()["items"] == []
    assert client.get(M).status_code == 401
    assert client.put(f"{M}/{SUP}", headers=sh(SUP)).status_code == 422  # own supplier


def test_cap_and_remute_at_cap(make_client):
    c = make_client(max_mutes_per_user=3, rate_posts=0)
    h = uh("viewer")
    for i in range(3):
        assert c.put(f"{M}/sup_{i}", headers=h).status_code == 200
    r = c.put(f"{M}/sup_extra", headers=h)
    assert r.status_code == 409 and "mute_limit_reached" in r.text
    assert c.put(f"{M}/sup_1", headers=h).status_code == 200  # already muted: idempotent at the cap
    assert c.put(f"{M}/sup_extra", headers=uh("other")).status_code == 200  # cap is per user
    c.delete(f"{M}/sup_0", headers=h)
    assert c.put(f"{M}/sup_extra", headers=h).status_code == 200


def test_filters_supplier_listing_home_trending_for_viewer_only(client):
    a = [post(client, f"Machine batch {i} available", SUP)["id"] for i in range(4)]
    b = [post(client, f"Resin lot {i} available", SUP2)["id"] for i in range(4)]
    v, other = uh("viewer"), uh("other")
    client.post(f"/v1/feed/suppliers/{SUP}/follow", headers=v)
    client.post(f"/v1/feed/suppliers/{SUP2}/follow", headers=v)
    client.put(f"/v1/feed/posts/{a[0]}/like", headers=other)
    client.put(f"{M}/{SUP}", headers=v)

    assert walk(client, f"/v1/feed/suppliers/{SUP}/posts", v) == []
    assert set(walk(client, "/v1/feed/home", v)) == set(b)
    assert set(walk(client, "/v1/feed/trending", v)) == set(b)
    # other viewers, anonymous, and the author still see them
    assert set(walk(client, f"/v1/feed/suppliers/{SUP}/posts", other)) == set(a)
    assert set(walk(client, f"/v1/feed/suppliers/{SUP}/posts", sh(SUP))) == set(a)
    assert set(a) <= set(walk(client, "/v1/feed/trending", other))
    # counts are not touched
    got = client.get(f"/v1/feed/posts/{a[0]}", headers=other).json()
    assert got["like_count"] == 1
    assert client.get(f"/v1/feed/suppliers/{SUP}/posts", headers=sh(SUP)).json()["items"][-1]["like_count"] == 1


def test_author_user_who_muted_own_supplier_still_sees_own_posts(client):
    mine = post(client, "Owner posting here today", SUP)
    owner = sh(SUP)
    client.put(f"{M}/sup_someone", headers=owner)
    # a different account (not the author) muting SUP
    client.put(f"{M}/{SUP}", headers=uh("fan"))
    assert mine["id"] in walk(client, f"/v1/feed/suppliers/{SUP}/posts", owner)
    assert mine["id"] not in walk(client, f"/v1/feed/suppliers/{SUP}/posts", uh("fan"))


def test_pagination_no_dupes_no_skips_with_muted_interleaved(client):
    posted = []
    for i in range(12):  # interleave suppliers so muted rows fall on every page boundary
        sup = SUP if i % 3 else SUP2
        posted.append((post(client, f"Interleaved offer number {i}", sup)["id"], sup))
    v = uh("viewer")
    client.post(f"/v1/feed/suppliers/{SUP2}/follow", headers=v)
    client.post(f"/v1/feed/suppliers/{SUP}/follow", headers=v)
    client.put(f"{M}/{SUP}", headers=v)
    want = [pid for pid, sup in reversed(posted) if sup == SUP2]
    for limit in (1, 2, 3):
        assert walk(client, "/v1/feed/home", v, limit) == want
        assert sorted(walk(client, "/v1/feed/trending", v, limit)) == sorted(want)
        assert len(set(walk(client, "/v1/feed/trending", v, limit))) == len(want)
    # muting every followed supplier: home falls back to trending, which is also filtered
    client.put(f"{M}/{SUP2}", headers=v)
    assert walk(client, "/v1/feed/home", v) == []
    assert walk(client, "/v1/feed/trending", v) == []


def test_unmute_restores(client):
    a = [post(client, f"Restorable item {i} listed", SUP)["id"] for i in range(5)]
    v = uh("viewer")
    client.put(f"{M}/{SUP}", headers=v)
    assert walk(client, f"/v1/feed/suppliers/{SUP}/posts", v) == []
    client.delete(f"{M}/{SUP}", headers=v)
    assert walk(client, f"/v1/feed/suppliers/{SUP}/posts", v, 2) == list(reversed(a))
    assert set(walk(client, "/v1/feed/trending", v)) == set(a)


def test_list_mutes_pagination_and_bad_cursor(client):
    v = uh("viewer")
    for i in range(5):
        client.put(f"{M}/sup_{i}", headers=v)
    seen, cursor = [], None
    while True:
        r = client.get(M, headers=v, params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        seen += [i["supplier_id"] for i in r["items"]]
        cursor = r["next_cursor"]
        if not cursor:
            break
    assert seen == [f"sup_{i}" for i in (4, 3, 2, 1, 0)]
    assert client.get(M, headers=v, params={"cursor": "garbage"}).status_code == 422


def test_privacy_erase_removes_mutes(make_client):
    c = make_client(rate_posts=0)
    v = uh("leaver")
    c.put(f"{M}/{SUP}", headers=v)
    exp = c.post("/v1/internal/users/leaver/export").json()
    assert [m["supplier_id"] for m in exp["data"]["mutes"]] == [SUP]
    out = c.delete("/v1/internal/users/leaver/data").json()
    assert out["counts"]["mutes_deleted"] == 1
    assert c.get(M, headers=v).json()["items"] == []
