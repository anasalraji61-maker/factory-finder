import pytest

from ff_logistics.domain import hs


def test_lookup_by_code(client):
    r = client.get("/v1/hs/854143")
    assert r.status_code == 200
    b = r.json()
    assert b["code"] == "854143" and b["chapter"] == "85"
    assert b["description_ar"] and b["description_en"]
    assert b["typical_duty_percent_hint"] == 5.0  # IQ chapter 85
    assert "indicative" in b["disclaimer"]


def test_lookup_dotted_and_country(client):
    r = client.get("/v1/hs/8517.13", params={"destination_country": "TR"})
    assert r.status_code == 200 and r.json()["code"] == "851713"
    assert r.json()["typical_duty_percent_hint"] == 3.0


def test_hint_null_when_chapter_not_in_table(client):
    r = client.get("/v1/hs/100630")
    assert r.status_code == 200 and r.json()["typical_duty_percent_hint"] is None


def test_unknown_code_404(client):
    r = client.get("/v1/hs/999999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_bad_code_422(client):
    assert client.get("/v1/hs/abc").status_code == 422


def test_search_english(client):
    b = client.get("/v1/hs/search", params={"q": "solar panels"}).json()
    assert b["items"][0]["code"] == "854143"
    b = client.get("/v1/hs/search", params={"q": "air conditioner"}).json()
    assert any(i["code"].startswith("8415") for i in b["items"][:3])


def test_search_arabic(client):
    b = client.get("/v1/hs/search", params={"q": "ألواح شمسية"}).json()
    assert b["items"][0]["code"] == "854143"
    b = client.get("/v1/hs/search", params={"q": "مولد ديزل"}).json()
    assert b["items"][0]["code"].startswith("8502")
    # normalization: ta marbuta / hamza / definite article
    assert hs.search("الثلاجه")[0].code.startswith("8418")


def test_search_code_prefix(client):
    b = client.get("/v1/hs/search", params={"q": "8517"}).json()
    assert b["items"] and all(i["code"].startswith("8517") for i in b["items"])


def test_search_limit_and_empty(client):
    assert len(client.get("/v1/hs/search", params={"q": "pump", "limit": 2}).json()["items"]) <= 2
    assert client.get("/v1/hs/search", params={"q": "   "}).status_code == 422
    assert client.get("/v1/hs/search").status_code == 422
    assert client.get("/v1/hs/search", params={"q": "x", "limit": 0}).status_code == 422
    assert client.get("/v1/hs/search", params={"q": "zzzqqq"}).json()["items"] == []


def test_dataset_integrity():
    meta, entries = hs.dataset()
    assert "indicative" in meta["note"] and len(entries) >= 300
    from ff_logistics.domain.duties import load_json
    raw = load_json("hs_codes.json")["items"]
    codes = [i["code"] for i in raw]
    assert len(codes) == len(set(codes))
    for i in raw:
        assert len(i["code"]) == 6 and i["code"].isdigit()
        assert i["chapter"] == i["code"][:2]
        assert i["description_en"].strip() and i["description_ar"].strip()
        assert i["keywords"]


@pytest.mark.parametrize("code", ["851713", "870380", "690722", "850760", "847710"])
def test_core_codes_present(code):
    assert hs.get(code) is not None
