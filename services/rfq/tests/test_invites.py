"""Invite-only requests: only listed verified suppliers (and the buyer) can see or offer; others get 404."""
import pytest
from conftest import BUYER, SUP_A, SUP_B, new_offer, new_request

INV = {**SUP_A, "X-Supplier-Id": "sup_a"}
OTHER = {**SUP_B, "X-Supplier-Id": "sup_b"}
OFFER = {"price": {"amount": "5", "currency": "USD"}, "supplier_name": "X"}


def _invite_only(client, **over):
    return new_request(client, invited_supplier_ids=["sup_a", "sup_a", "sup_c"], **over)


def test_invited_supplier_sees_and_offers(client):
    req = _invite_only(client)
    assert req["invited_supplier_ids"] == ["sup_a", "sup_c"]  # de-duplicated, buyer view
    rid = req["id"]
    d = client.get(f"/v1/requests/{rid}", headers=INV)
    assert d.status_code == 200 and "invited_supplier_ids" not in d.json()
    listed = client.get("/v1/requests?scope=public", headers=INV).json()
    assert rid in [i["id"] for i in listed["items"]]
    assert all("invited_supplier_ids" not in i for i in listed["items"])
    assert new_offer(client, rid, headers=INV)["supplier_ref"] == "sup_a"
    assert client.get(f"/v1/requests/{rid}/offers", headers=INV).status_code == 200
    mine = client.get("/v1/requests?scope=mine", headers=BUYER).json()["items"][0]
    assert mine["invited_supplier_ids"] == ["sup_a", "sup_c"]
    assert client.get(f"/v1/requests/{rid}", headers=BUYER).json()["invited_supplier_ids"] == ["sup_a", "sup_c"]


@pytest.mark.parametrize("hdrs", [OTHER, SUP_B, {**SUP_B, "X-Supplier-Id": "sup_A"}, {**SUP_B, "X-Supplier-Id": "sup_a "[:5] + "x"}])
def test_idor_non_invited_gets_404(client, hdrs):
    rid = _invite_only(client)["id"]
    assert client.get(f"/v1/requests/{rid}", headers=hdrs).status_code == 404
    assert client.post(f"/v1/requests/{rid}/offers", json=OFFER, headers=hdrs).status_code == 404
    assert client.get(f"/v1/requests/{rid}/offers", headers=hdrs).status_code == 404
    items = client.get("/v1/requests?scope=public", headers=hdrs).json()["items"]
    assert rid not in [i["id"] for i in items]
    assert client.get(f"/v1/requests/{rid}/suggestions", headers=hdrs).status_code == 403


def test_user_id_equal_to_invited_id_is_not_enough(client):
    # an unverified caller (no X-Supplier-Id) whose user id equals an invited supplier id gets nothing
    rid = _invite_only(client)["id"]
    assert client.get(f"/v1/requests/{rid}", headers={"X-User-Id": "sup_a"}).status_code == 404
    assert client.post(f"/v1/requests/{rid}/offers", json=OFFER, headers={"X-User-Id": "sup_a"}).status_code == 404


def test_not_invited_cannot_probe_after_prior_offer_state(client):
    # offers made before... a non-invited user cannot gain access by any route; unknown id looks identical
    rid = _invite_only(client, visibility="public")["id"]
    a = client.post(f"/v1/requests/{rid}/offers", json=OFFER, headers=OTHER)
    b = client.post("/v1/requests/req_nope/offers", json=OFFER, headers=OTHER)
    assert a.status_code == b.status_code == 404
    assert a.json() == b.json()


def test_public_requests_unchanged_and_empty_list_is_public(client):
    pub = new_request(client)
    assert pub["invited_supplier_ids"] == []
    pub2 = new_request(client, invited_supplier_ids=[])
    for rid in (pub["id"], pub2["id"]):
        assert client.get(f"/v1/requests/{rid}", headers=OTHER).status_code == 200
        new_offer(client, rid, headers=OTHER)
    ids = [i["id"] for i in client.get("/v1/requests?scope=public", headers=SUP_B).json()["items"]]
    assert pub["id"] in ids and pub2["id"] in ids


def test_private_without_invites_unchanged(client):
    rid = new_request(client, visibility="private")["id"]
    assert client.get(f"/v1/requests/{rid}", headers=OTHER).status_code == 404
    assert rid not in [i["id"] for i in client.get("/v1/requests?scope=public", headers=OTHER).json()["items"]]


def test_private_invite_only_visible_to_invitee(client):
    rid = _invite_only(client, visibility="private")["id"]
    assert client.get(f"/v1/requests/{rid}", headers=INV).status_code == 200
    assert rid in [i["id"] for i in client.get("/v1/requests?scope=public", headers=INV).json()["items"]]


@pytest.mark.parametrize("bad", [["x"] * 51 + ["y"], ["a" * 65], ["bad id"], ["../x"], [""], [1], "sup_a"])
def test_invite_validation(client, bad):
    body = {"kind": "product", "title": "LED panel", "quantity": "1", "invited_supplier_ids": bad}
    assert client.post("/v1/requests", json=body, headers=BUYER).status_code == 422


def test_fifty_invites_ok(client):
    ids = [f"s{i}" for i in range(50)]
    assert len(new_request(client, invited_supplier_ids=ids)["invited_supplier_ids"]) == 50
