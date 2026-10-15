"""Seeded property-style tests: pagination stability, ordering invariants, self-engagement, caps."""

import random

import pytest
from conftest import SUP, post, sh, uh  # noqa: F401


def walk(client, url, headers=None, limit=3, between=None):
    seen, cursor, n = [], None, 0
    while True:
        page = client.get(f"{url}?limit={limit}" + (f"&cursor={cursor}" if cursor else ""), headers=headers or {}).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        n += 1
        if not cursor:
            return seen
        assert n < 100
        if between:
            between(n)


@pytest.mark.parametrize("seed", range(6))
def test_trending_pagination_stable_under_concurrent_engagement(client, clock, seed):
    rnd = random.Random(seed)
    ids = []
    for i in range(14):
        ids.append(post(client, f"post {seed} {i}", supplier=f"sup_{rnd.randrange(4)}")["id"])
        clock.advance(hours=rnd.choice([0, 1, 30, 50]))
    for _ in range(25):
        client.put(f"/v1/feed/posts/{rnd.choice(ids)}/like", headers=uh(f"u{rnd.randrange(8)}"))
    expected_n = len(client.get("/v1/feed/trending?limit=50").json()["items"])
    assert expected_n >= 5

    def churn(_):  # likes / comments land between page fetches
        for _ in range(4):
            pid = rnd.choice(ids)
            client.put(f"/v1/feed/posts/{pid}/like", headers=uh(f"x{rnd.randrange(50)}"))
            client.post(f"/v1/feed/posts/{pid}/comments", headers=uh(f"y{rnd.randrange(50)}"), json={"body": f"c{rnd.random()}"})

    seen = walk(client, "/v1/feed/trending", limit=rnd.choice([1, 2, 3, 5]), between=churn)
    assert len(seen) == len(set(seen)) == expected_n  # no duplicates, no skips


@pytest.mark.parametrize("seed", range(4))
def test_trending_ordering_invariant_and_determinism(client, seed):
    rnd = random.Random(100 + seed)
    ids = [post(client, f"p {seed} {i}")["id"] for i in range(10)]
    for _ in range(30):
        client.put(f"/v1/feed/posts/{rnd.choice(ids)}/like", headers=uh(f"u{rnd.randrange(9)}"))
    a = client.get("/v1/feed/trending?limit=50").json()["items"]
    b = client.get("/v1/feed/trending?limit=50").json()["items"]
    assert [i["id"] for i in a] == [i["id"] for i in b]
    assert [i["like_count"] for i in a] == sorted((i["like_count"] for i in a), reverse=True)  # all fresh: same boost


def test_self_engagement_does_not_rank(client):
    mine = post(client, "mine")
    other = post(client, "other", supplier="sup_beta")
    owner = sh(SUP)
    for _ in range(3):
        client.put(f"/v1/feed/posts/{mine['id']}/like", headers=owner)
        client.post(f"/v1/feed/posts/{mine['id']}/comments", headers=owner, json={"body": "bump"})
    client.put(f"/v1/feed/posts/{other['id']}/like", headers=uh("fan"))
    got = [i["id"] for i in client.get("/v1/feed/trending").json()["items"]]
    assert got == [other["id"], mine["id"]]
    client.delete(f"/v1/feed/posts/{mine['id']}/like", headers=owner)  # unlike keeps stored score consistent


def test_new_supplier_post_not_buried_by_old_popular(client, clock):
    old = post(client, "old popular", supplier="sup_old")["id"]
    for u in range(6):
        client.put(f"/v1/feed/posts/{old}/like", headers=uh(f"f{u}"))
    clock.advance(days=3)
    new = post(client, "brand new", supplier="sup_new")["id"]
    got = [i["id"] for i in client.get("/v1/feed/trending").json()["items"]]
    assert got == [old, new]  # boost is bounded: popular still leads, newcomer is ahead of zero-score old posts
    clock.advance(days=3)
    zero_old = post(client, "zero", supplier="sup_z")["id"]
    clock.advance(days=2)
    fresh = post(client, "fresh", supplier="sup_new")["id"]
    got = [i["id"] for i in client.get("/v1/feed/trending").json()["items"]]
    assert got.index(fresh) < got.index(zero_old)


def test_page_size_capped(client):
    for i in range(5):
        post(client, f"v {i}")
    page = client.get("/v1/feed/trending?limit=100000", headers=uh("v"))
    assert page.status_code in (200, 422)
    if page.status_code == 200:
        assert len(page.json()["items"]) <= 50
