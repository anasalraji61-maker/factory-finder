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


def test_keywords_no_duplicate_hs6_and_well_formed():
    items = load_json("hs_keywords.json")["items"]
    codes = [i["hs6"] for i in items]
    assert len(codes) == len(set(codes)), "duplicate hs6 in hs_keywords.json"
    for i in items:
        assert len(i["hs6"]) == 6 and i["hs6"].isdigit() and i["hs6"].isascii(), i["hs6"]
        assert i["description_ar"].strip() and i["description_en"].strip(), i["hs6"]


def test_asgi_live_style_arabic_cotton_fabric():
    import asyncio

    import httpx

    from ff_logistics.main import create_app

    async def go():
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            return await c.get("/v1/hs/suggest", params={"q": "قماش قطن"})

    r = asyncio.run(go())
    assert r.status_code == 200
    b = r.json()
    assert set(b) == {"items", "total", "indicative", "disclaimer"}
    assert b["indicative"] is True and b["total"] == len(b["items"]) >= 1
    for it in b["items"]:
        assert set(it) == {"hs6", "description_en", "description_ar", "confidence", "note"}
    assert any(it["hs6"].startswith("52") for it in b["items"]), b["items"]
