import pytest
from conftest import ADM, APP, make_forwarder, uh


def apply(client, user="u1", **over):
    return client.post("/v1/freight/applications", headers=uh(user), json={**APP, **over})


def test_apply_pending_then_admin_approve_creates_forwarder(client):
    r = apply(client)
    assert r.status_code == 201
    a = r.json()
    assert a["status"] == "pending" and a["forwarder_id"] is None and "user_id" not in a
    assert a["modes"] == ["sea", "air"] and a["incoterms"] == ["FOB", "CIF", "EXW"]
    assert client.get("/v1/freight/me", headers=uh("u1")).json()["forwarder_id"] is None
    assert client.get("/v1/freight/forwarders/me", headers=uh("u1")).status_code == 403
    listed = client.get("/v1/admin/freight/applications", headers=ADM).json()["items"]
    assert [i["id"] for i in listed] == [a["id"]] and listed[0]["user_id"] == "u1"
    ok = client.post(f"/v1/admin/freight/applications/{a['id']}/approve", headers=ADM, json={"note": "docs checked"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    fid = ok.json()["forwarder_id"]
    me = client.get("/v1/freight/me", headers=uh("u1")).json()
    assert me == {"user_id": "u1", "forwarder_id": fid, "forwarder_status": "active"}
    prof = client.get("/v1/freight/forwarders/me", headers=uh("u1")).json()
    assert prof["id"] == fid and prof["status"] == "active" and "user_id" not in prof
    assert prof["lanes"] == [
        {"origin_country": "CN", "destination_country": "AE"},
        {"origin_country": "CN", "destination_country": "IQ"},
    ]
    assert prof["rating"] == {"average": None, "count": 0}
    # approve is idempotent and never makes a second forwarder
    again = client.post(f"/v1/admin/freight/applications/{a['id']}/approve", headers=ADM)
    assert again.status_code == 200 and again.json()["forwarder_id"] == fid
    assert len(client.get("/v1/admin/freight/forwarders", headers=ADM).json()["items"]) == 1
    mine = client.get("/v1/freight/applications/mine", headers=uh("u1")).json()["items"]
    assert mine[0]["status"] == "approved"


def test_apply_conflicts(client):
    a = apply(client).json()
    assert apply(client).status_code == 409 and apply(client).json()["error"]["code"] == "application_pending"
    client.post(f"/v1/admin/freight/applications/{a['id']}/approve", headers=ADM)
    r = apply(client)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_forwarder"


def test_reject_then_reapply_and_cap(make_client):
    c = make_client(rate_applications=0, admin_token="adm-secret", max_applications_per_user=2)
    a = apply(c).json()
    r = c.post(f"/v1/admin/freight/applications/{a['id']}/reject", headers=ADM, json={"reason": "no licence"})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["review_note"] == "no licence"
    assert c.post(f"/v1/admin/freight/applications/{a['id']}/reject", headers=ADM, json={"reason": "again"}).status_code == 200
    assert c.post(f"/v1/admin/freight/applications/{a['id']}/approve", headers=ADM).status_code == 409
    b = apply(c).json()  # may reapply after a rejection
    assert b["id"] != a["id"]
    c.post(f"/v1/admin/freight/applications/{b['id']}/reject", headers=ADM, json={"reason": "no licence"})
    r = apply(c)
    assert r.status_code == 409 and r.json()["error"]["code"] == "application_limit_reached"
    assert c.post(f"/v1/admin/freight/applications/{b['id']}/approve", headers=ADM).status_code == 409


def test_approved_application_cannot_be_rejected(client):
    a = apply(client).json()
    client.post(f"/v1/admin/freight/applications/{a['id']}/approve", headers=ADM)
    assert client.post(f"/v1/admin/freight/applications/{a['id']}/reject", headers=ADM, json={"reason": "oops"}).status_code == 409
    assert client.post("/v1/admin/freight/applications/app_nope/approve", headers=ADM).status_code == 404
    assert client.post("/v1/admin/freight/applications/app_nope/reject", headers=ADM, json={"reason": "abc"}).status_code == 404


@pytest.mark.parametrize(
    "over",
    [
        {"company_name": "x"},
        {"country_code": "ae"},
        {"lanes": []},
        {"lanes": [{"origin_country": "CNN", "destination_country": "IQ"}]},
        {"modes": []},
        {"modes": ["teleport"]},
        {"incoterms": ["XYZ"]},
        {"certifications": ["<script>"]},
        {"unknown": 1},
        {"lanes": [{"origin_country": "CN", "destination_country": "IQ"}] * 51},
    ],
)
def test_apply_validation(client, over):
    assert apply(client, **over).status_code == 422


@pytest.mark.parametrize(
    "over",
    [
        {"description": "email us at sales@gulfstar.com"},
        {"description": "call +964 770 123 4567"},
        {"description": "see www.gulfstar.com"},
        {"company_name": "Gulf Star dot com"},
        {"description": "we move firearms and ammunition"},
        {"certifications": ["whatsapp 123"]},
    ],
)
def test_apply_screening(client, over):
    r = apply(client, **over)
    assert r.status_code == 422 and r.json()["error"]["code"] == "content_rejected"
    assert "sales@gulfstar" not in r.text and "4567" not in r.text


def test_lane_cap_from_settings(make_client):
    c = make_client(rate_applications=0, max_lanes_per_forwarder=1, admin_token="x")
    r = apply(c)
    assert r.status_code == 422 and r.json()["error"]["code"] == "lane_limit_exceeded"


def test_application_dedupes_lanes_modes(client):
    lane = {"origin_country": "CN", "destination_country": "IQ"}
    a = apply(client, lanes=[lane, lane], modes=["sea", "sea"], certifications=["FIATA", "FIATA"]).json()
    assert len(a["lanes"]) == 1 and a["modes"] == ["sea"] and a["certifications"] == ["FIATA"]


def test_profile_update_and_directory(client):
    f1 = make_forwarder(client, "u1")
    f2 = make_forwarder(
        client, "u2", company_name="Euro Cargo", country_code="DE",
        lanes=[{"origin_country": "*", "destination_country": "IQ"}], modes=["road"], incoterms=["DAP"],
    )  # fmt: skip
    r = client.patch("/v1/freight/forwarders/me", headers=uh("u1"), json={"description": "Updated", "modes": ["sea"]})
    assert r.status_code == 200 and r.json()["description"] == "Updated" and r.json()["modes"] == ["sea"]
    r = client.patch(
        "/v1/freight/forwarders/me", headers=uh("u1"),
        json={"lanes": [{"origin_country": "US", "destination_country": "JO"}]},
    )  # fmt: skip
    assert r.json()["lanes"] == [{"origin_country": "US", "destination_country": "JO"}]
    for bad in ({"lanes": None}, {"modes": None}, {"incoterms": None}, {"company_name": "New"}, {"modes": []}):
        assert client.patch("/v1/freight/forwarders/me", headers=uh("u1"), json=bad).status_code == 422
    assert client.patch("/v1/freight/forwarders/me", headers=uh("u1"), json={"description": "mail a@b.co"}).status_code == 422
    assert client.patch("/v1/freight/forwarders/me", headers=uh("nobody"), json={"description": "x"}).status_code == 403

    def ids(**q):
        return {i["id"] for i in client.get("/v1/freight/forwarders", headers=uh("anyone"), params=q).json()["items"]}

    assert ids() == {f1, f2}
    assert ids(origin_country="CN") == {f2}  # f2 wildcard origin; f1 now US->JO
    assert ids(origin_country="US", destination_country="JO") == {f1}
    assert ids(destination_country="IQ") == {f2}
    assert ids(mode="road") == {f2} and ids(mode="sea") == {f1}
    assert ids(incoterm="DAP") == {f2} and ids(incoterm="DDP") == set()
    assert client.get("/v1/freight/forwarders", headers=uh("a"), params={"mode": "boat"}).status_code == 422
    assert client.get("/v1/freight/forwarders", headers=uh("a"), params={"origin_country": "cn"}).status_code == 422
    pub = client.get(f"/v1/freight/forwarders/{f1}", headers=uh("anyone")).json()
    assert pub["company_name"] == "Gulf Star Logistics" and "status" not in pub and "user_id" not in pub


def test_directory_pagination_and_suspension(client):
    ids = [make_forwarder(client, f"u{i}") for i in range(5)]
    seen, cur = [], None
    while True:
        r = client.get("/v1/freight/forwarders", headers=uh("x"), params={"limit": 2, **({"cursor": cur} if cur else {})}).json()
        seen += [i["id"] for i in r["items"]]
        cur = r["next_cursor"]
        if not cur:
            break
    assert seen == ids[::-1]
    assert client.get("/v1/freight/forwarders", headers=uh("x"), params={"cursor": "junk"}).json()["error"]["code"] == "invalid_cursor"
    s = client.post(f"/v1/admin/freight/forwarders/{ids[0]}/suspend", headers=ADM, json={"reason": "licence expired"})
    assert s.json()["status"] == "suspended" and s.json()["status_reason"].startswith("admin:")
    assert ids[0] not in {i["id"] for i in client.get("/v1/freight/forwarders", headers=uh("x"), params={"limit": 50}).json()["items"]}
    assert client.get(f"/v1/freight/forwarders/{ids[0]}", headers=uh("x")).status_code == 404
    assert client.get(f"/v1/freight/forwarders/{ids[0]}", headers=uh("u0")).json()["status"] == "suspended"  # owner still sees it
    assert client.get("/v1/admin/freight/forwarders?status=suspended", headers=ADM).json()["items"][0]["id"] == ids[0]
    r = client.post(f"/v1/admin/freight/forwarders/{ids[0]}/reinstate", headers=ADM)
    assert r.json()["status"] == "active" and r.json()["status_reason"] is None
    assert client.post("/v1/admin/freight/forwarders/fwd_nope/suspend", headers=ADM, json={"reason": "abc"}).status_code == 404
