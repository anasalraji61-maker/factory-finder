from conftest import H

BODY = {"reference": "CSQU3054383", "reference_type": "container"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "service": "tracking", "version": "0.1.0"}


def test_validate_endpoint(client):
    ok = client.get("/v1/validate/container/MSCU6639870").json()
    assert "valid" in ok
    good = client.get("/v1/validate/awb/176-12345675").json()
    assert good["valid"] and good["carrier"]["code"] == "emirates" and good["mode"] == "air"
    bad = client.get("/v1/validate/vessel_imo/9074728").json()
    assert not bad["valid"] and bad["reason"] == "check_digit"
    assert client.get("/v1/validate/nope/x").status_code == 422


def test_requires_user(client):
    r = client.get("/v1/shipments")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


def test_create_get_list_delete(client):
    r = client.post("/v1/shipments", json={**BODY, "label": "Order 7"}, headers=H)
    assert r.status_code == 201
    sh = r.json()
    assert sh["id"].startswith("shp_") and sh["mode"] == "sea" and sh["events"]
    assert sh["carrier"] is None or sh["carrier"]["name"]
    assert 0 < sh["progress_percent"] <= 100
    assert client.get(f"/v1/shipments/{sh['id']}", headers=H).json()["id"] == sh["id"]
    page = client.get("/v1/shipments?page_size=5", headers=H).json()
    assert page["total"] == 1 and page["items"][0]["id"] == sh["id"]
    assert client.get(f"/v1/shipments?status={sh['status']}", headers=H).json()["total"] == 1
    assert client.delete(f"/v1/shipments/{sh['id']}", headers=H).status_code == 204
    assert client.get(f"/v1/shipments/{sh['id']}", headers=H).status_code == 404


def test_carrier_detected_from_container_prefix(client):
    from ff_tracking.domain.validators import container_check_digit

    ref = "MSCU639870"
    r = client.post("/v1/shipments", json={"reference": ref + str(container_check_digit(ref)),
                                           "reference_type": "container"}, headers=H)
    assert r.json()["carrier"]["code"] == "msc"


def test_invalid_duplicate_and_ownership(client):
    bad = client.post("/v1/shipments", json={**BODY, "reference": "CSQU3054384"}, headers=H)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_reference"
    sid = client.post("/v1/shipments", json=BODY, headers=H).json()["id"]
    dup = client.post("/v1/shipments", json=BODY, headers=H)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "duplicate_shipment"
    other = {"X-User-Id": "usr_b"}
    assert client.get(f"/v1/shipments/{sid}", headers=other).status_code == 404
    assert client.post(f"/v1/shipments/{sid}/refresh", headers=other).status_code == 404
    assert client.get("/v1/shipments", headers=other).json()["total"] == 0
    assert client.post("/v1/shipments", json=BODY, headers=other).status_code == 201


def test_refresh_throttling_and_progress(client, clock):
    sid = client.post("/v1/shipments", json=BODY, headers=H).json()["id"]
    r = client.post(f"/v1/shipments/{sid}/refresh", headers=H)
    assert r.status_code == 429 and r.json()["error"]["code"] == "refresh_throttled"
    assert int(r.headers["Retry-After"]) > 0
    clock.advance(seconds=61)
    first = client.post(f"/v1/shipments/{sid}/refresh", headers=H)
    assert first.status_code == 200
    assert client.post(f"/v1/shipments/{sid}/refresh", headers=H).status_code == 429
    clock.advance(days=120)
    done = client.post(f"/v1/shipments/{sid}/refresh", headers=H).json()
    assert done["status"] == "delivered" and done["progress_percent"] == 100
    assert len(done["events"]) > len(first.json()["events"])


def test_air_and_imo_shipments(client):
    air = client.post("/v1/shipments", json={"reference": "176-12345675", "reference_type": "awb"}, headers=H).json()
    assert air["mode"] == "air" and air["carrier"]["code"] == "emirates"
    imo = client.post("/v1/shipments", json={"reference": "IMO9074729", "reference_type": "vessel_imo"}, headers=H).json()
    assert imo["reference"] == "9074729"
