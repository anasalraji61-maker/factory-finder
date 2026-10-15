from decimal import Decimal

from conftest import make_forwarder, make_quote, make_request, uh

from ff_freight.ranking import Candidate, normalise_weights, rank, shrunk_rating

W = normalise_weights(50, 30, 20)


def cand(qid, amount, days, rs=0, rc=0, key="a"):
    return Candidate(qid, Decimal(amount), days, rs, rc, key)


def test_weights_normalise():
    assert normalise_weights(50, 30, 20) == (Decimal("0.5"), Decimal("0.3"), Decimal("0.2"))
    assert normalise_weights(1, 1, 0) == (Decimal("0.5"), Decimal("0.5"), Decimal("0"))
    assert normalise_weights(0, 0, 0) == (Decimal("0.5"), Decimal("0.3"), Decimal("0.2"))  # degenerate -> defaults


def test_shrunk_rating_prior():
    assert shrunk_rating(0, 0) == Decimal(3)
    assert shrunk_rating(5, 1) == Decimal(11) / 3  # one 5-star does not give 5.0
    assert shrunk_rating(500, 100) > Decimal("4.9")


def test_rank_math_is_exact_and_explained():
    rows = rank([cand("a", "1000", 20), cand("b", "800", 40), cand("c", "1200", 10, 50, 10)], W)
    by = {r["quote_id"]: r for r in rows}
    # a: price 0.8, transit 0.5, rating 0.6 -> 100*(0.4+0.15+0.12)=67.0
    assert by["a"]["score"] == Decimal("67.0")
    # b: price 1.0, transit 0.25, rating 0.6 -> 100*(0.5+0.075+0.12)=69.5
    assert by["b"]["score"] == Decimal("69.5")
    # c: price 0.6667, transit 1.0, rating (50+6)/12/5=0.9333 -> 100*(0.3333+0.3+0.1867)=82.0
    assert by["c"]["score"] == Decimal("82.0")
    assert [r["quote_id"] for r in rows] == ["c", "b", "a"] and [r["rank"] for r in rows] == [1, 2, 3]
    assert by["b"]["badges"] == ["cheapest"] and by["c"]["badges"] == ["fastest", "top_rated"] and by["a"]["badges"] == []
    assert by["c"]["breakdown"]["rating"]["weight"] == Decimal("0.200")
    assert len(by["a"]["explanation"]) == 5 and "price 80% of best" in by["a"]["explanation"][0]
    assert "best fastest, top rated" in by["c"]["explanation"][3]


def test_sort_modes_and_tie_breaks():
    cs = [cand("a", "100", 30, key="1"), cand("b", "100", 30, key="2"), cand("c", "90", 50, key="3"), cand("d", "150", 5, 25, 5, key="4")]
    assert [r["quote_id"] for r in rank(cs, W, "price")] == ["c", "a", "b", "d"]
    assert [r["quote_id"] for r in rank(cs, W, "transit")] == ["d", "a", "b", "c"]
    assert [r["quote_id"] for r in rank(cs, W, "rating")][0] == "d"
    default = [r["quote_id"] for r in rank(cs, W)]
    assert default.index("a") < default.index("b")  # exact tie -> earlier submission first
    assert rank([], W) == []


def test_single_candidate_scores_full_price_and_transit():
    (r,) = rank([cand("a", "500", 7)], W)
    assert r["score"] == Decimal("92.0") and set(r["badges"]) == {"cheapest", "fastest"}


def _three(client):
    for u in ("cheap", "fast", "rated"):
        make_forwarder(client, u)
    req = make_request(client)
    q = {
        "cheap": make_quote(client, req["id"], "cheap", amount="1000", transit_days=40)["id"],
        "fast": make_quote(client, req["id"], "fast", amount="1500", transit_days=10)["id"],
        "rated": make_quote(client, req["id"], "rated", amount="1300", transit_days=25)["id"],
    }
    return req, q


def test_comparison_endpoint(client):
    req, q = _three(client)
    r = client.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1"))
    assert r.status_code == 200
    body = r.json()
    assert body["currency"] == "USD" and body["sort"] == "score" and "formula" in body
    assert body["weights"] == {"price": 0.5, "transit": 0.3, "rating": 0.2}
    assert [i["rank"] for i in body["items"]] == [1, 2, 3]
    scores = [i["score"] for i in body["items"]]
    assert scores == sorted(scores, reverse=True)
    top = body["items"][0]
    assert set(top) >= {"rank", "score", "breakdown", "badges", "explanation", "quote", "adjusted_rating"}
    assert top["quote"]["forwarder"]["company_name"]
    by_price = client.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1"), params={"sort": "price"}).json()
    assert [i["quote"]["id"] for i in by_price["items"]] == [q["cheap"], q["rated"], q["fast"]]
    by_transit = client.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1"), params={"sort": "transit"}).json()
    assert by_transit["items"][0]["quote"]["id"] == q["fast"] and "fastest" in by_transit["items"][0]["badges"]
    assert client.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1"), params={"sort": "luck"}).status_code == 422
    assert client.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("cheap")).status_code == 404
    assert client.get("/v1/freight/requests/shp_nope/comparison", headers=uh("buyer1")).status_code == 404


def test_ratings_move_the_ranking(client):
    """A forwarder with completed, well-rated jobs outranks an equal unrated one."""
    make_forwarder(client, "good")
    make_forwarder(client, "new")
    done = make_request(client, user="b0")
    qd = make_quote(client, done["id"], "good")
    client.post(f"/v1/freight/quotes/{qd['id']}/accept", headers=uh("b0"))
    client.post(f"/v1/freight/requests/{done['id']}/close", headers=uh("b0"))
    client.post(f"/v1/freight/requests/{done['id']}/rating", headers=uh("b0"), json={"stars": 5})
    req = make_request(client)
    make_quote(client, req["id"], "new")
    qg = make_quote(client, req["id"], "good")
    items = client.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1")).json()["items"]
    assert items[0]["quote"]["id"] == qg["id"] and items[0]["adjusted_rating"] > items[1]["adjusted_rating"]
    assert "top_rated" not in items[0]["badges"] and items[0]["rating_confidence"] == "low"  # one rating is not enough


def test_comparison_after_award_keeps_accepted_only(client):
    req, q = _three(client)
    client.post(f"/v1/freight/quotes/{q['fast']}/accept", headers=uh("buyer1"))
    body = client.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1")).json()
    assert body["request_status"] == "awarded" and [i["quote"]["id"] for i in body["items"]] == [q["fast"]]


def test_weights_configurable(make_client):
    from conftest import NO_LIMITS

    c = make_client(**{**NO_LIMITS, "weight_price": 100, "weight_transit": 0, "weight_rating": 0})
    req, q = _three(c)
    body = c.get(f"/v1/freight/requests/{req['id']}/comparison", headers=uh("buyer1")).json()
    assert body["weights"] == {"price": 1.0, "transit": 0.0, "rating": 0.0}
    assert body["items"][0]["quote"]["id"] == q["cheap"]
