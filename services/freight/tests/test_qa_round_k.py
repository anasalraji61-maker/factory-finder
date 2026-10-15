"""QA round K: Bayesian rating aggregation, quote validity boundary, ranking explainability consistency."""

from datetime import timedelta
from decimal import Decimal

from conftest import NO_LIMITS, Clock, make_forwarder, make_quote, make_request, uh
from fastapi.testclient import TestClient

from ff_freight.config import Settings
from ff_freight.main import create_app
from ff_freight.ranking import Candidate, normalise_weights, rank, shrunk_rating

W = normalise_weights(50, 30, 20)


def cand(qid, amount, days, rs=0, rc=0, key="a"):
    return Candidate(qid, Decimal(amount), days, rs, rc, key)


class Frozen(Clock):
    def __call__(self):
        return self.t


def frozen_client():
    clock = Frozen()
    c = TestClient(create_app(Settings(database_url="sqlite+aiosqlite:///:memory:", **NO_LIMITS), clock=clock))
    c.__enter__()
    return c, clock


# ---- Bayesian shrink -----------------------------------------------------------------------
def test_shrink_properties():
    assert shrunk_rating(30, 10) == Decimal(36) / 12  # avg 3.0 stays 3.0
    assert shrunk_rating(30, 10) == Decimal(3)
    # above the prior mean it is pulled down, below it pulled up, and more evidence pulls less
    assert Decimal(3) < shrunk_rating(5, 1) < Decimal(5)
    assert Decimal(1) < shrunk_rating(1, 1) < Decimal(3)
    assert shrunk_rating(5, 1) < shrunk_rating(10, 2) < shrunk_rating(50, 10) < Decimal(5)
    assert Decimal(3) > shrunk_rating(1, 1) > shrunk_rating(2, 2) > shrunk_rating(10, 10) > Decimal(1)
    # a 100-review 4.5 beats a 2-review 5.0
    assert shrunk_rating(450, 100) > shrunk_rating(10, 2)


def test_rating_score_normalised_into_unit_interval():
    (lo, hi) = rank([cand("lo", "100", 10, 100, 100), cand("hi", "100", 10, 500, 100)], W)[::-1]
    assert Decimal(0) <= lo["breakdown"]["rating"]["value"] < hi["breakdown"]["rating"]["value"] <= Decimal(1)


def test_top_rated_badge_needs_five_ratings_and_is_unique_best():
    rows = rank([cand("a", "100", 10, 20, 4), cand("b", "100", 10, 25, 5), cand("c", "100", 10, 24, 5)], W)
    badges = {r["quote_id"]: r["badges"] for r in rows}
    assert "top_rated" not in badges["a"] and "top_rated" in badges["b"] and "top_rated" not in badges["c"]


def test_ratings_endpoint_aggregates_average_and_adjusted(make_client_k=None):
    c, clock = frozen_client()
    make_forwarder(c, "fw")
    for i, stars in enumerate((5, 4)):
        r = make_request(c, user=f"b{i}")
        q = make_quote(c, r["id"], "fw")
        assert c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh(f"b{i}")).status_code == 200
        assert c.post(f"/v1/freight/requests/{r['id']}/close", headers=uh(f"b{i}")).status_code == 200
        assert c.post(f"/v1/freight/requests/{r['id']}/rating", headers=uh(f"b{i}"), json={"stars": stars}).status_code == 201
    fid = c.get("/v1/freight/forwarders/me", headers=uh("fw")).json()["id"]
    f = c.get(f"/v1/freight/forwarders/{fid}", headers=uh("buyer1")).json()
    assert f["rating"] == {"average": "4.50", "count": 2}
    req = make_request(c)
    make_quote(c, req["id"], "fw")
    (item,) = c.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1")).json()["items"]
    assert item["adjusted_rating"] == 3.75  # (9 + 3*2) / (2 + 2)
    assert item["rating_count"] == 2 and item["rating_confidence"] == "low"
    assert any("3.75/5 after shrinking" in e for e in item["explanation"])
    c.__exit__(None, None, None)


# ---- quote validity boundary -----------------------------------------------------------------
def test_quote_validity_exact_second_boundary():
    c, clock = frozen_client()
    make_forwarder(c, "fw")
    req = make_request(c)
    q = make_quote(c, req["id"], "fw", valid_days=1)
    until = clock.t + timedelta(days=1)

    def cmp():
        return c.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1")).json()

    clock.t = until - timedelta(seconds=1)
    assert c.get(f"/v1/freight/quotes/{q['id']}", headers=uh("buyer1")).json()["valid"] is True
    assert [i["quote"]["id"] for i in cmp()["items"]] == [q["id"]] and cmp()["excluded"] == []
    clock.t = until  # valid_until is exclusive: at that exact instant the quote is gone
    assert c.get(f"/v1/freight/quotes/{q['id']}", headers=uh("buyer1")).json()["valid"] is False
    body = cmp()
    assert body["items"] == [] and [e["reason"] for e in body["excluded"]] == ["quote_expired"]
    r = c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh("buyer1"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "quote_expired"
    assert c.post("/v1/admin/freight/sweep", headers={"X-Admin-Token": "adm-secret", "X-User-Id": "admin"}).status_code in (200, 404)
    c.__exit__(None, None, None)


def test_accept_one_second_before_validity_end_works():
    c, clock = frozen_client()
    make_forwarder(c, "fw")
    req = make_request(c)
    q = make_quote(c, req["id"], "fw", valid_days=1)
    clock.t = clock.t + timedelta(days=1) - timedelta(seconds=1)
    assert c.post(f"/v1/freight/quotes/{q['id']}/accept", headers=uh("buyer1")).status_code == 200
    c.__exit__(None, None, None)


# ---- explainability consistency ----------------------------------------------------------------
def test_explanation_fields_match_numbers():
    cs = [cand("a", "1000", 20, 30, 6), cand("b", "800", 40), cand("c", "1200", 10, 50, 10), cand("d", "800", 40, key="b")]
    for sort in ("score", "price", "transit", "rating"):
        rows = rank(cs, W, sort)
        assert sorted(r["rank"] for r in rows) == [1, 2, 3, 4]
        for r in rows:
            b = r["breakdown"]
            recomputed = 100 * sum(b[k]["value"] * b[k]["weight"] for k in b)
            assert abs(recomputed - r["score"]) <= Decimal("0.2")
            assert sum(b[k]["weight"] for k in b) == Decimal("1.000")
            n_cheaper = len([x for x in cs if Decimal(x.amount) < Decimal(next(y.amount for y in cs if y.quote_id == r["quote_id"]))])
            assert len(r["cheaper_quote_ids"]) == n_cheaper
            assert (r["price_delta"] == 0) == ("cheapest" in r["badges"])
            assert ("cheaper quote" in " ".join(r["explanation"])) == bool(n_cheaper)
            assert (r["rating_confidence"] == "established") == (r["rating_count"] >= 5)
    by = {r["quote_id"]: r for r in rank(cs, W)}
    assert by["a"]["cheaper_quote_ids"] == ["b", "d"] and by["a"]["price_delta"] == Decimal(200)
    assert "cheapest" in by["b"]["badges"] and "cheapest" in by["d"]["badges"]  # tied cheapest both badged
    assert by["c"]["rating_confidence"] == "established" and by["a"]["rating_confidence"] == "established"
    assert by["b"]["rating_confidence"] == "unrated"


def test_comparison_inclusion_diff_fields(client=None):
    c, clock = frozen_client()
    for u in ("f1", "f2"):
        make_forwarder(c, u)
    req = make_request(c)
    make_quote(c, req["id"], "f1", inclusions=["Ocean freight", "Insurance"])
    make_quote(c, req["id"], "f2", inclusions=["Ocean freight", "Origin THC"])
    items = c.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1")).json()["items"]
    by = {i["quote"]["forwarder"]["company_name"] + str(n): i for n, i in enumerate(items)}
    for i in items:
        assert "Ocean freight" not in i["inclusions_unique"] and "Ocean freight" not in i["inclusions_missing"]
        assert len(i["inclusions_unique"]) == 1 and len(i["inclusions_missing"]) == 1
        assert i["inclusions_unique"] != i["inclusions_missing"]
    assert by
    c.__exit__(None, None, None)
