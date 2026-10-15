"""Verified-deal reviews: eligibility, one per deal, IDOR, 24h windows, spam filters, aggregates."""

import pytest
from conftest import BUYER, SUP_A, SUP_B, new_offer, new_request
from sqlalchemy import select, update

from ff_rfq.db import DealRow, ReviewEventRow
from ff_rfq.domain.review_text import average, detect_contact, reviewer_display, sanitize

SUP_REF = "sup_a"
SUP_A_V = {**SUP_A, "X-Supplier-Id": SUP_REF}
BUYER_N = {**BUYER, "X-User-Name": "Ahmed%20Karim"}


def set_status(client, deal_id, status):
    async def run():
        eng = client.app.state.service.engine
        async with eng.begin() as conn:
            await conn.execute(update(DealRow).where(DealRow.id == deal_id).values(status=status))

    client.portal.call(run)


def make_deal(client, status="completed", buyer=BUYER, sup=SUP_A_V, amount="12.50"):
    req = new_request(client)
    off = new_offer(client, req["id"], sup, amount)
    # the helper's buyer is always BUYER; other buyers are covered through IDOR tests
    d = client.post(f"/v1/offers/{off['id']}/accept", headers=buyer).json()
    if status:
        set_status(client, d["id"], status)
    return d


def post_review(client, deal_id, headers=BUYER_N, **over):
    return client.post(f"/v1/deals/{deal_id}/reviews", json={"rating": 5, **over}, headers=headers)


def test_eligibility_by_deal_status(client):
    d = make_deal(client, status=None)  # pending_payment
    r = post_review(client, d["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "deal_not_reviewable"
    for st in ("disputed", "cancelled"):
        set_status(client, d["id"], st)
        assert post_review(client, d["id"]).status_code == 409
    for st in ("paid", "in_fulfilment", "completed"):
        d2 = make_deal(client, status=st)
        assert post_review(client, d2["id"]).status_code == 201


def test_only_buyer_idor_and_unknown(client):
    d = make_deal(client)
    assert post_review(client, d["id"], SUP_A_V).status_code == 403  # the supplier of the deal
    assert post_review(client, d["id"], SUP_B).status_code == 404  # stranger: no existence leak
    assert post_review(client, "deal_nope").status_code == 404
    assert client.post(f"/v1/deals/{d['id']}/reviews", json={"rating": 5}).status_code == 401


def test_unverified_supplier_deal_not_reviewable(client):
    d = make_deal(client, sup=SUP_A)  # no X-Supplier-Id on the offer
    r = post_review(client, d["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "supplier_unverified"


def test_create_shape_and_duplicate(client):
    d = make_deal(client)
    r = post_review(client, d["id"], title="Great", text="Fast delivery, well packed.",
                    sub_ratings={"quality": 5, "shipping": 4})
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["id"].startswith("rev_") and b["supplier_ref"] == SUP_REF and b["rating"] == 5
    assert b["reviewer"] == "Ahmed K." and "buyer1" not in str(b) and b["verified_purchase"] is True
    assert b["sub_ratings"] == {"quality": 5, "communication": None, "shipping": 4}
    assert b["mine"] is True and b["editable_until"] == "2026-10-02T12:00:00Z" and b["reply"] is None
    dup = post_review(client, d["id"])
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "review_already_exists"
    # deleting does not free the slot (one review per deal, ever)
    assert client.delete(f"/v1/reviews/{b['id']}", headers=BUYER).status_code == 200
    assert post_review(client, d["id"]).status_code == 409


@pytest.mark.parametrize("body", [
    {"rating": 0}, {"rating": 6}, {"rating": 4.5}, {"rating": "5"}, {"rating": True}, {},
    {"rating": 5, "title": "x" * 81}, {"rating": 5, "text": "x" * 1001},
    {"rating": 5, "sub_ratings": {"quality": 6}}, {"rating": 5, "sub_ratings": {"speed": 3}},
    {"rating": 5, "extra": 1},
])
def test_validation(client, body):
    d = make_deal(client)
    r = client.post(f"/v1/deals/{d['id']}/reviews", json=body, headers=BUYER_N)
    assert r.status_code == 422 and r.json()["error"]["code"] in ("validation_error",)


def test_limits_accept_boundaries(client):
    d = make_deal(client)
    assert post_review(client, d["id"], title="t" * 80, text="é" * 1000).status_code == 201


@pytest.mark.parametrize("text", [
    "see http://spam.example/x", "visit www.shop-now.com", "mail me bob@example.com", "bob (at) gmail",
    "call +964 770 123 4567", "whatsapp 07701234567", "رقمي ٠٧٧٠١٢٣٤٥٦٧", "go to buy-cheap.shop today",
    "t.me/scammer", "ｈｔｔｐ：／／evil.example", "ftp://x.y",
])
def test_spam_filters_422(client, text):
    d = make_deal(client)
    for field in ("text", "title"):
        r = post_review(client, d["id"], **{field: text[:80]})
        assert r.status_code == 422 and r.json()["error"]["code"] == "prohibited_content", (field, text)
    assert post_review(client, d["id"]).status_code == 201  # nothing was stored by the failed attempts


def test_innocent_text_passes_and_control_chars_stripped(client):
    d = make_deal(client)
    txt = "Ordered 1000 pieces on 2026-10-01. Good, e.g. packaging.‮evil​\x00\x07 ok"
    b = post_review(client, d["id"], text=txt, title="  ‮Nice⁦  ").json()
    assert b["title"] == "Nice" and b["text"] == "Ordered 1000 pieces on 2026-10-01. Good, e.g. packaging.evil ok"


def test_blank_text_becomes_null(client):
    d = make_deal(client)
    b = post_review(client, d["id"], text="  ​ ", title="").json()
    assert b["text"] is None and b["title"] is None


def test_edit_and_delete_windows(client, clock):
    d = make_deal(client)
    rid = post_review(client, d["id"], text="ok").json()["id"]
    clock.advance(hours=23, minutes=59)
    e = client.put(f"/v1/reviews/{rid}", json={"rating": 3, "text": "changed my mind"}, headers=BUYER)
    assert e.status_code == 200 and e.json()["rating"] == 3 and e.json()["edited"] is True
    assert client.put(f"/v1/reviews/{rid}", json={"rating": 2}, headers=SUP_B).status_code == 403
    clock.advance(hours=0, minutes=1)  # exactly 24h: still allowed
    assert client.put(f"/v1/reviews/{rid}", json={"rating": 4}, headers=BUYER).status_code == 200
    clock.advance(seconds=1)
    for r in (client.put(f"/v1/reviews/{rid}", json={"rating": 1}, headers=BUYER),
              client.delete(f"/v1/reviews/{rid}", headers=BUYER)):
        assert r.status_code == 409 and r.json()["error"]["code"] == "review_window_closed"
    s = client.get(f"/v1/suppliers/{SUP_REF}/review-summary").json()
    assert s["count"] == 1 and s["average"] == "4.00"


def test_delete_stops_counting_and_keeps_audit(client):
    d = make_deal(client)
    rid = post_review(client, d["id"], rating=1, text="bad").json()["id"]
    assert client.get(f"/v1/suppliers/{SUP_REF}/review-summary").json()["count"] == 1
    assert client.delete(f"/v1/reviews/{rid}", headers=SUP_B).status_code == 403
    assert client.delete(f"/v1/reviews/{rid}", headers=BUYER).json() == {"id": rid, "status": "deleted"}
    assert client.get(f"/v1/suppliers/{SUP_REF}/review-summary").json()["count"] == 0
    assert client.get(f"/v1/suppliers/{SUP_REF}/reviews").json()["total"] == 0
    assert client.delete(f"/v1/reviews/{rid}", headers=BUYER).status_code == 404
    assert client.put(f"/v1/reviews/{rid}", json={"rating": 5}, headers=BUYER).status_code == 404
    assert client.post(f"/v1/reviews/{rid}/reply", json={"text": "hi"}, headers=SUP_A_V).status_code == 404

    async def events():
        async with client.app.state.service.engine.connect() as c:
            rows = (await c.execute(select(ReviewEventRow.action, ReviewEventRow.snapshot)
                                    .order_by(ReviewEventRow.created_at))).all()
        return rows

    rows = client.portal.call(events)
    assert [r[0] for r in rows] == ["created", "deleted"] and rows[1][1]["text"] == "bad"


def test_edit_keeps_prior_values_in_audit(client):
    d = make_deal(client)
    rid = post_review(client, d["id"], rating=2, text="meh").json()["id"]
    client.put(f"/v1/reviews/{rid}", json={"rating": 5, "text": "better"}, headers=BUYER)

    async def events():
        async with client.app.state.service.engine.connect() as c:
            return (await c.execute(select(ReviewEventRow.action, ReviewEventRow.snapshot))).all()

    edited = [r for r in client.portal.call(events) if r[0] == "edited"]
    assert edited[0][1]["rating"] == 2 and edited[0][1]["text"] == "meh"


def test_reply_authorization_and_once(client):
    d = make_deal(client)
    rid = post_review(client, d["id"]).json()["id"]
    body = {"text": "Thank you for your order."}
    assert client.post(f"/v1/reviews/{rid}/reply", json=body, headers=BUYER).status_code == 403
    assert client.post(f"/v1/reviews/{rid}/reply", json=body, headers=SUP_A).status_code == 403  # unverified
    assert client.post(f"/v1/reviews/{rid}/reply", json=body, headers={**SUP_B, "X-Supplier-Id": "sup_b"}).status_code == 403
    assert client.post(f"/v1/reviews/{rid}/reply", json={"text": "call 0770123456789"}, headers=SUP_A_V).status_code == 422
    assert client.post(f"/v1/reviews/{rid}/reply", json={"text": "x" * 501}, headers=SUP_A_V).status_code == 422
    assert client.post(f"/v1/reviews/{rid}/reply", json={"text": " ​"}, headers=SUP_A_V).status_code == 422
    ok = client.post(f"/v1/reviews/{rid}/reply", json=body, headers=SUP_A_V)
    assert ok.status_code == 201 and ok.json()["reply"]["text"] == body["text"]
    again = client.post(f"/v1/reviews/{rid}/reply", json={"text": "more"}, headers=SUP_A_V)
    assert again.status_code == 409 and again.json()["error"]["code"] == "reply_already_exists"
    pub = client.get(f"/v1/suppliers/{SUP_REF}/reviews").json()["items"][0]
    assert pub["reply"]["text"] == body["text"]


def test_report_flags_never_hides_and_is_rate_limited(client, clock):
    d = make_deal(client)
    rid = post_review(client, d["id"]).json()["id"]
    assert client.post(f"/v1/reviews/{rid}/report", json={}, headers=BUYER).status_code == 403  # own review
    r = client.post(f"/v1/reviews/{rid}/report", json={"reason": "spam", "note": "looks fake"}, headers=SUP_B)
    assert r.status_code == 200 and r.json() == {"id": rid, "flagged_for_review": True, "already_reported": False}
    again = client.post(f"/v1/reviews/{rid}/report", json={}, headers=SUP_B).json()
    assert again["already_reported"] is True
    assert client.post(f"/v1/reviews/{rid}/report", json={"reason": "bogus"}, headers=SUP_B).status_code == 422
    assert client.get(f"/v1/suppliers/{SUP_REF}/review-summary").json()["count"] == 1  # still counted
    assert client.get(f"/v1/suppliers/{SUP_REF}/reviews").json()["total"] == 1  # still visible
    assert client.get(f"/v1/suppliers/{SUP_REF}/reviews", headers=BUYER).json()["items"][0]["flagged_for_review"] is True
    assert client.get(f"/v1/suppliers/{SUP_REF}/reviews").json()["items"][0]["flagged_for_review"] is None
    ids = [rid] + [post_review(client, make_deal(client)["id"]).json()["id"] for _ in range(10)]
    codes = [client.post(f"/v1/reviews/{i}/report", json={}, headers={"X-User-Id": "rep"}).status_code for i in ids]
    assert codes == [200] * 10 + [429]
    clock.advance(hours=1, seconds=1)
    assert client.post(f"/v1/reviews/{ids[-1]}/report", json={}, headers={"X-User-Id": "rep"}).status_code == 200
    assert client.post("/v1/reviews/rev_nope/report", json={}, headers=SUP_B).status_code == 404
    assert client.post(f"/v1/reviews/{rid}/report", json={}).status_code == 401


def test_summary_math_and_histogram(client, clock):
    empty = client.get(f"/v1/suppliers/{SUP_REF}/review-summary")
    assert empty.status_code == 200 and empty.json() == {
        "supplier_ref": SUP_REF, "count": 0, "average": None, "histogram": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0},
        "sub_ratings": {"quality": None, "communication": None, "shipping": None}, "completed_deals": 0,
        "first_review_at": None, "last_review_at": None}
    ratings = [5, 5, 4, 4, 4, 1, 3]  # sum 26 / 7 = 3.714... -> 3.71
    for i, rt in enumerate(ratings):
        d = make_deal(client, status="completed" if i < 5 else "paid")
        subs = {"quality": rt} if i < 3 else None
        assert post_review(client, d["id"], rating=rt, sub_ratings=subs).status_code == 201
        if i == 0:
            clock.advance(hours=2)
    s = client.get(f"/v1/suppliers/{SUP_REF}/review-summary").json()
    assert s["first_review_at"] < s["last_review_at"] and s["first_review_at"].endswith("Z")
    assert s["count"] == 7 and s["average"] == "3.71"
    assert s["histogram"] == {"1": 1, "2": 0, "3": 1, "4": 3, "5": 2}
    assert s["sub_ratings"] == {"quality": "4.67", "communication": None, "shipping": None}
    assert s["completed_deals"] == 5
    other = client.get("/v1/suppliers/sup_other/review-summary").json()
    assert other["count"] == 0 and other["completed_deals"] == 0


def test_average_rounding_half_up():
    assert average(9, 2) == "4.50" and average(1, 8) == "0.13" and average(5, 3) == "1.67"
    assert average(0, 0) is None and average(25, 6) == "4.17" and average(1, 200) == "0.01"
    assert average(401, 200) == "2.01"  # 2.005 rounds half up, binary floats would give 2.00


def test_list_pagination_and_sort(client, clock):
    ids = []
    for rt in (3, 5, 1, 4, 2):
        d = make_deal(client)
        ids.append(post_review(client, d["id"], rating=rt).json()["id"])
        clock.advance(minutes=1)
    p1 = client.get(f"/v1/suppliers/{SUP_REF}/reviews?page=1&page_size=2").json()
    assert [i["rating"] for i in p1["items"]] == [2, 4] and p1["total"] == 5 and p1["page"] == 1
    p3 = client.get(f"/v1/suppliers/{SUP_REF}/reviews?page=3&page_size=2").json()
    assert [i["rating"] for i in p3["items"]] == [3]
    byr = client.get(f"/v1/suppliers/{SUP_REF}/reviews?sort=rating&page_size=5").json()
    assert [i["rating"] for i in byr["items"]] == [5, 4, 3, 2, 1]
    assert client.get(f"/v1/suppliers/{SUP_REF}/reviews?sort=bogus").status_code == 422
    assert client.get(f"/v1/suppliers/{SUP_REF}/reviews?page_size=101").status_code == 422
    assert client.get(f"/v1/suppliers/{SUP_REF}/reviews?page=0").status_code == 422
    assert client.get(f"/v1/suppliers/{'x' * 65}/reviews").status_code == 422
    assert client.get("/v1/suppliers/nobody/reviews").json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_public_reads_leak_no_private_data(client):
    d = make_deal(client)
    post_review(client, d["id"], text="fine")
    raw = client.get(f"/v1/suppliers/{SUP_REF}/reviews").text
    for secret in ("buyer1", "supA", d["id"], "deal_", "karim", "Karim"):
        assert secret not in raw
    item = client.get(f"/v1/suppliers/{SUP_REF}/reviews").json()["items"][0]
    assert item["mine"] is False and item["editable_until"] is None


def test_reviewer_display_and_sanitize_units():
    assert reviewer_display("Ahmed Karim") == "Ahmed K."
    assert reviewer_display("ahmed bin ali karim") == "ahmed K."
    assert reviewer_display("Anas") == "Anas"
    assert reviewer_display("أنس الراجي") == "أنس ا."
    assert reviewer_display(None) == "Verified buyer" and reviewer_display("a@b.com") == "Verified buyer"
    assert reviewer_display("www.x.com Smith") == "Verified buyer"
    assert sanitize("a‮b\x00c\r\n\r\n\r\n\r\nd") == "abc\n\nd"
    assert detect_contact("nice 12 34 56") is None and detect_contact("a@b.co") == "url"
    assert detect_contact("write to bob@mail") == "email" and detect_contact("great product. thanks") is None


def _refund(client, d, n):
    body = {"invoice_id": "inv_dp", "kind": "deal_payment", "status": "refunded",
            "amount": d["subtotal"], "event_id": f"evt_hide_{n}", "other_open_kinds": []}
    r = client.post(f"/v1/internal/deals/{d['id']}/payment-status", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("status,expect", [("paid", "refunded"), ("in_fulfilment", "disputed")])
def test_refund_or_dispute_hides_review(client, status, expect):
    d = make_deal(client, status=status)
    rid = post_review(client, d["id"], rating=1).json()["id"]
    assert client.get(f"/v1/suppliers/{SUP_REF}/review-summary").json()["count"] == 1
    assert _refund(client, d, status)["deal_status"] == expect
    assert client.get(f"/v1/suppliers/{SUP_REF}/review-summary").json()["count"] == 0
    assert client.get(f"/v1/suppliers/{SUP_REF}/reviews").json()["total"] == 0
    assert client.put(f"/v1/reviews/{rid}", json={"rating": 5}, headers=BUYER).status_code == 404

    async def rows():
        async with client.app.state.service.engine.begin() as conn:
            from ff_rfq.db import ReviewRow
            st = (await conn.execute(select(ReviewRow.status, ReviewRow.flagged_for_review))).one()
            ev = (await conn.execute(select(ReviewEventRow.action).where(ReviewEventRow.review_id == rid))).scalars().all()
            return st, ev

    st, ev = client.portal.call(rows)
    assert tuple(st) == ("hidden", True) and "hidden" in ev


def test_free_text_control_chars_stripped(client):
    req = new_request(client, title="LED\x00 pan\x07el‮ lights", description="line1\x00\nline2​",
                      unit="pi\x00ece", destination={"country_code": "IQ", "city": "Bagh\x07dad"})
    assert (req["title"], req["description"], req["unit"]) == ("LED panel lights", "line1\nline2", "piece")
    assert req["destination"]["city"] == "Baghdad"
    off = new_offer(client, req["id"], SUP_A, supplier_name="Ac\x00me‮ Ltd", notes="ok\x07​notes")
    assert off["supplier_name"] == "Acme Ltd" and off["notes"] == "oknotes"
    bad = client.post("/v1/requests", json={"kind": "product", "title": "\x00\x00\x00\x00", "quantity": "1"}, headers=BUYER)
    assert bad.status_code == 422
