import json

from ff_logistics.domain import hs_suggest as hs
from ff_logistics.domain.duties import load_json


def top(q):
    r = hs.suggest_hs(q)
    return r[0]["hs6"] if r else None


def test_english_arabic_chinese():
    assert top("solar panel") == "854143"
    assert top("ألواح شمسية") == "854143"
    assert top("太阳能电池板") == "854143"
    assert top("air conditioner") == "841510"
    assert top("مكيف") == "841510"
    assert top("空调") == "841510"
    assert top("lithium batteries") == "850760"


def test_items_shape_and_indicative():
    for q in ["rice", "ثلاجة", "手机", "washing machine"]:
        for it in hs.suggest_hs(q):
            assert set(it) == {"hs6", "description_en", "description_ar", "confidence", "note"}
            assert it["confidence"] in ("low", "medium") and "indicative" in it["note"]
            assert "not an official classification" in it["note"]


def test_empty_and_garbage():
    for q in ["", "   ", "!!!@@##", "zzzxqj", "\x00\x01", "😀😀"]:
        assert hs.suggest_hs(q) == []
    assert hs.suggest_hs(None) == []  # type: ignore[arg-type]


def test_long_input_is_bounded_fast():
    assert isinstance(hs.suggest_hs("a" * 100000 + " " + "(a+)+$" * 5000), list)
    assert isinstance(hs.suggest_hs("太" * 100000), list)


def test_limit_clamped():
    assert len(hs.suggest_hs("machine", limit=1)) <= 1
    assert len(hs.suggest_hs("machine", limit=9999)) <= hs.MAX_LIMIT


def test_data_integrity():
    d = load_json("hs_keywords.json")
    assert "indicative" in d["note"] and len(d["items"]) >= 150
    codes = [i["hs6"] for i in d["items"]]
    assert len(codes) == len(set(codes)) and all(len(c) == 6 and c.isdigit() for c in codes)
    for i in d["items"]:
        assert i["description_en"] and i["description_ar"]
        assert all(i["keywords"][k] for k in ("en", "ar", "zh")), i["hs6"]
    json.dumps(d, ensure_ascii=False)


def test_endpoint(client):
    b = client.get("/v1/hs/suggest", params={"q": "太阳能电池板"}).json()
    assert b["indicative"] is True and b["items"][0]["hs6"] == "854143"
    assert client.get("/v1/hs/suggest", params={"q": "ثلاجة", "limit": 2}).json()["total"] <= 2
    assert client.get("/v1/hs/suggest", params={"q": "zzzxqj"}).json()["items"] == []


def test_endpoint_bounds(client):
    assert client.get("/v1/hs/suggest").status_code == 422
    assert client.get("/v1/hs/suggest", params={"q": " "}).status_code == 422
    assert client.get("/v1/hs/suggest", params={"q": "a" * 101}).status_code == 422
    assert client.get("/v1/hs/suggest", params={"q": "a" * 100}).status_code == 200
    assert client.get("/v1/hs/suggest", params={"q": "rice", "limit": 21}).status_code == 422
    assert client.get("/v1/hs/suggest", params={"q": "rice", "limit": 0}).status_code == 422
