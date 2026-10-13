async def test_health(client):
    r = await client.get("/health")
    assert r.json() == {"status": "ok", "service": "sourcing", "version": "0.1.0"}


async def test_search_shape_and_money_is_string(client):
    r = await client.get("/v1/search", params={"q": "air conditioner", "page_size": 5})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "total", "page", "page_size", "sources"}
    item = body["items"][0]
    assert (
        isinstance(item["price"]["min"]["amount"], str)
        and item["price"]["min"]["currency"] == "USD"
    )
    assert item["images"][0].startswith("https://picsum.photos/seed/lst_")
    assert "description" not in item


async def test_search_validation_errors(client):
    for params in (
        {"kind": "bogus"},
        {"page": 0},
        {"page_size": 1000},
        {"min_price": 10, "max_price": 5},
    ):
        r = await client.get("/v1/search", params=params)
        assert r.status_code == 422 and "code" in r.json()["error"]


async def test_listing_detail_and_404(client):
    r = await client.get("/v1/listings/lst_0001")
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == "lst_0001" and d["description"] and d["specs"]["HS code"] == "8438.10"
    assert d["supplier"]["trust_band"] in ("green", "yellow", "red")
    r = await client.get("/v1/listings/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "listing_not_found"


async def test_supplier_endpoint(client):
    r = await client.get("/v1/suppliers/sup_cn_012")
    s = r.json()
    assert (
        r.status_code == 200 and s["listing_count"] == 2 and s["location"]["country_code"] == "CN"
    )
    assert (await client.get("/v1/suppliers/sup_zz_999")).status_code == 404


async def test_categories_bilingual(client):
    tree = (await client.get("/v1/categories")).json()
    assert [n["slug"] for n in tree] == ["product", "raw_material", "production_line"]
    assert all(n["name_ar"] and c["name_ar"] for n in tree for c in n["children"])


async def test_sources_listing(client, app):
    from ff_sourcing.adapters.registry import build_registry
    from ff_sourcing.config import Settings

    app.state.service.registry = build_registry(Settings())
    src = {s["id"]: s for s in (await client.get("/v1/sources")).json()}
    assert src["mock"]["enabled"] and src["mock"]["status"] == "ok"
    for sid in ("alibaba", "made_in_china", "aliexpress", "source_1688"):
        assert (
            not src[sid]["enabled"]
            and src[sid]["status"] == "disabled"
            and not src[sid]["configured"]
        )
