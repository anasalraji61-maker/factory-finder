"""QA round 3 edge cases: empty, duplicate, oversized, unicode."""

import pytest
from conftest import H

BODY = {"reference": "CSQU3054383", "reference_type": "container"}


def test_empty_list_and_pagination_past_end(client):
    j = client.get("/v1/shipments", headers=H).json()
    assert j["items"] == [] and j["total"] == 0
    assert client.get("/v1/shipments?page=99999", headers=H).json()["items"] == []


@pytest.mark.parametrize("q", ["page=0", "page=-1", "page=x", "page_size=0", "page_size=101", "status=bogus"])
def test_bad_query_params_are_422(client, q):
    assert client.get(f"/v1/shipments?{q}", headers=H).status_code == 422


@pytest.mark.parametrize("ref", [" csqu 3054383 ", "csqu3054383", "CSQU-3054383", "CSQU3054383\n"])
def test_equivalent_spellings_are_duplicates(client, ref):
    assert client.post("/v1/shipments", json=BODY, headers=H).status_code == 201
    r = client.post("/v1/shipments", json={**BODY, "reference": ref}, headers=H)
    assert r.status_code in (409, 422), r.text  # never a second shipment
    assert client.get("/v1/shipments", headers=H).json()["total"] == 1


def test_duplicate_after_delete_can_be_recreated(client):
    sid = client.post("/v1/shipments", json=BODY, headers=H).json()["id"]
    assert client.delete(f"/v1/shipments/{sid}", headers=H).status_code == 204
    assert client.delete(f"/v1/shipments/{sid}", headers=H).status_code == 404
    assert client.post("/v1/shipments", json=BODY, headers=H).status_code == 201


@pytest.mark.parametrize("field,n", [("reference", 65), ("carrier", 81), ("label", 121)])
def test_oversized_fields_rejected(client, field, n):
    r = client.post("/v1/shipments", json={**BODY, field: "A" * n}, headers=H)
    assert r.status_code == 422


def test_oversized_path_ids_rejected(client):
    assert client.get("/v1/shipments/" + "s" * 65, headers=H).status_code == 422
    assert client.get("/v1/validate/container/" + "A" * 65).status_code == 422


@pytest.mark.parametrize("ref", ["", "ab", "ا" * 11, "١٢٣٤٥٦٧", "CSQU３０５４３８３", "CSQU3054383​", "CSQU‮3054383", "💥" * 5])
def test_unicode_and_junk_references_never_500(client, ref):
    r = client.post("/v1/shipments", json={**BODY, "reference": ref}, headers=H)
    assert r.status_code in (201, 409, 422), (ref, r.status_code, r.text)
    v = client.get(f"/v1/validate/container/{ref}") if ref else None
    if v is not None:
        assert v.status_code in (200, 404, 422)
    if r.status_code == 201:  # accepted only when it normalises to the canonical container number
        assert r.json()["reference"] == "CSQU3054383"


def test_unicode_label_roundtrips_and_control_chars_stripped(client):
    r = client.post("/v1/shipments", json={**BODY, "label": "طلبية البصرة ١ 🚢\x00\x07"}, headers=H)
    assert r.status_code == 201
    label = r.json()["label"]
    assert "طلبية البصرة" in label and "\x00" not in label and "\x07" not in label


def test_unicode_user_header_rejected(client):
    r = client.get("/v1/shipments", headers={"X-User-Id": "مستخدم".encode()})
    assert r.status_code == 401
    assert client.get("/v1/shipments", headers={"X-User-Id": "   "}).status_code == 401
    assert client.get("/v1/shipments", headers={"X-User-Id": "u" * 129}).status_code == 401


def test_users_do_not_collide_on_same_reference_across_case(client):
    assert client.post("/v1/shipments", json=BODY, headers={"X-User-Id": "usr_a"}).status_code == 201
    assert client.post("/v1/shipments", json=BODY, headers={"X-User-Id": "USR_A"}).status_code == 201


def test_invalid_body_shapes(client):
    assert client.post("/v1/shipments", json={}, headers=H).status_code == 422
    assert client.post("/v1/shipments", json={**BODY, "extra": 1}, headers=H).status_code == 422
    assert client.post("/v1/shipments", content=b"\xff\xfe", headers={**H, "Content-Type": "application/json"}).status_code in (400, 422)
