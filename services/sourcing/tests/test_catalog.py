from decimal import Decimal

from ff_sourcing.adapters.mock import MockAdapter, load_catalog
from ff_sourcing.domain.categories import expand_category
from ff_sourcing.domain.models import SearchQuery

COUNTRIES = {"CN", "US", "DE", "IT", "TR", "IN", "VN"}


async def test_catalog_integrity():
    cat = load_catalog()
    ids = [x["id"] for x in cat["listings"]]
    assert len(ids) == len(set(ids)) >= 60
    sup_ids = {s["id"] for s in cat["suppliers"]}
    assert len(sup_ids) == len(cat["suppliers"])
    items = await MockAdapter().search(SearchQuery(limit=500))
    assert {i.kind for i in items} == {"product", "raw_material", "production_line"}
    assert {i.condition for i in items} >= {"new", "used"}
    leaf = {c for k in ("product", "raw_material", "production_line") for c in expand_category(k)}
    for i in items:
        assert i.id.startswith("lst_") and len(i.id) == 8
        assert i.supplier.id in sup_ids and i.supplier.id.startswith("sup_")
        assert 0 < i.price.min.amount <= i.price.max.amount
        assert i.price.min.amount > Decimal(0) and i.price.min.currency == "USD"
        assert i.title_ar and any("؀" <= ch <= "ۿ" for ch in i.title_ar)
        assert i.category in leaf
        assert i.moq and i.moq > 0 and i.unit and i.hs_code and i.incoterm
        assert i.unit_weight_kg > 0 and i.unit_volume_m3 > 0
        assert 0 < i.lead_time_days.min <= i.lead_time_days.max
        assert i.images[0] == f"https://picsum.photos/seed/{i.id}/600/600"
    assert {i.origin.country_code for i in items} == COUNTRIES
    cn = sum(1 for i in items if i.origin.country_code == "CN")
    assert cn > len(items) / 2
    assert all(i.condition == "new" for i in items if i.origin.country_code == "CN")
    assert all(i.condition != "new" for i in items if i.origin.country_code in ("DE", "IT"))
