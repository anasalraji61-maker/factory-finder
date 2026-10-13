def test_get_and_patch_profile(client, hdr):
    r = client.patch("/v1/me", headers=hdr, json={
        "name": "Anas R", "company": "ACME", "role": "both", "language": "en", "display_currency": "IQD",
        "phone": "+964 750 111 2222", "default_destination": {"country_code": "IQ", "city": "Basra", "point": {"lat": 30.5, "lon": 47.8}},
    })  # fmt: skip
    assert r.status_code == 200
    me = client.get("/v1/me", headers=hdr).json()
    assert me["role"] == "both" and me["language"] == "en" and me["display_currency"] == "IQD"
    assert me["phone"] == "+9647501112222" and me["default_destination"]["city"] == "Basra"
    # partial update keeps the rest
    client.patch("/v1/me", headers=hdr, json={"company": "NewCo"})
    me = client.get("/v1/me", headers=hdr).json()
    assert me["company"] == "NewCo" and me["role"] == "both"


def test_patch_validation(client, hdr):
    for bad in [
        {"role": "admin"}, {"language": "fr"}, {"display_currency": "usd"}, {"phone": "abc"},
        {"default_destination": {"country_code": "iraq"}}, {"unknown": 1}, {"name": ""},
        {"default_destination": {"country_code": "IQ", "point": {"lat": 99, "lon": 0}}},
    ]:  # fmt: skip
        r = client.patch("/v1/me", headers=hdr, json=bad)
        assert r.status_code == 422, bad
        assert r.json()["error"]["code"] == "validation_error"


def test_patch_null_required_and_conflicts(client, hdr):
    assert client.patch("/v1/me", headers=hdr, json={"role": None}).status_code == 422
    client.post("/v1/auth/register", json={"email": "b@example.com", "password": "password123", "name": "B"})
    r = client.patch("/v1/me", headers=hdr, json={"email": "b@example.com"})
    assert r.status_code == 409
    # cannot remove the only contact
    assert client.patch("/v1/me", headers=hdr, json={"email": None}).status_code == 422


def test_home_feed_with_mock_client(client, hdr):
    r = client.get("/v1/home", headers=hdr)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["name"] == "Anas" and body["categories"] and body["trending"] and body["warnings"] == []
    assert client.get("/v1/home").status_code == 401
