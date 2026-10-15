import pytest


@pytest.mark.parametrize(
    "qs",
    [
        "min_price=NaN", "min_price=Infinity", "min_price=-1", "max_price=1e999999",
        "origin_country=12", "origin_country=1%C3%A9", "category=" + "a" * 101,
        "moq_max=99999999999999999999", "page=0", "page_size=101", "min_price=5&max_price=1",
    ],
)
async def test_search_rejects_bad_params(client, qs):
    r = await client.get(f"/v1/search?{qs}")
    assert r.status_code == 422, qs
    assert r.json()["error"]["code"] in ("validation_error", "invalid_price_range")


async def test_huge_page_is_empty_not_error(client):
    r = await client.get("/v1/search?page=100000000&page_size=100")
    assert r.status_code == 200 and r.json()["items"] == []


async def test_overlong_ids_rejected(client):
    for path in ("listings", "suppliers"):
        assert (await client.get(f"/v1/{path}/{'a' * 129}")).status_code == 422
    assert (await client.get(f"/v1/listings/{'a' * 129}/similar")).status_code == 422
    assert (await client.get(f"/v1/listings/{'a' * 129}/price-history")).status_code == 422
