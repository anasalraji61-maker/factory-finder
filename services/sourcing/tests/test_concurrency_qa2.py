"""QA2: concurrent import / publish on a file-backed sqlite DB."""

import asyncio

import httpx
import pytest
from sqlalchemy import func, select

from ff_sourcing.adapters.mock import MockAdapter
from ff_sourcing.adapters.registry import AdapterRegistry
from ff_sourcing.clients.trust import MockTrustClient, TrustInfo
from ff_sourcing.config import Settings
from ff_sourcing.db import NativeListingRow
from ff_sourcing.main import create_app

A = {"X-Supplier-Id": "sup_native_a"}
IMP = "/v1/my/listings/import"
GREEN = TrustInfo(supplier_id="x", score=90, band="green")


def item(ref):
    return {
        "external_ref": ref, "kind": "product", "condition": "new", "title": "Zebrafish ceramic planter",
        "description": "Hand glazed.", "category": "furniture",
        "price": {"min": {"amount": "2.50", "currency": "USD"}, "max": {"amount": "4.10", "currency": "USD"}},
        "unit": "piece", "moq": 100, "incoterm": "FOB", "unit_weight_kg": 1.2, "unit_volume_m3": 0.01,
        "hs_code": "691390", "lead_time_days": {"min": 10, "max": 20},
        "images": ["https://cdn.example.com/a.jpg"], "origin": {"country_code": "IQ", "city": "Baghdad"},
    }


@pytest.fixture
async def fc(tmp_path):
    app = create_app(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 's.db'}"),
                     AdapterRegistry([MockAdapter()]), MockTrustClient({"sup_native_a": GREEN}))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.app = app
        yield c


async def _rows(c):
    async with c.app.state.native.store.sm() as s:
        return (await s.execute(select(NativeListingRow.external_ref, func.count())
                                .group_by(NativeListingRow.external_ref))).all()


async def test_concurrent_imports_same_refs_one_row_each(fc):
    items = [item(f"R{i}") for i in range(5)]
    rs = await asyncio.gather(*[fc.post(IMP, json={"items": items}, headers=A) for _ in range(6)])
    assert all(r.status_code == 200 for r in rs), [r.text for r in rs]
    assert sorted(await _rows(fc)) == [(f"R{i}", 1) for i in range(5)]
    assert sum(r.json()["created"] for r in rs) == 5  # each ref created exactly once across racing imports


async def test_concurrent_publish_is_idempotent(fc):
    r = await fc.post("/v1/my/listings", json={k: v for k, v in item("X1").items() if k != "external_ref"}, headers=A)
    assert r.status_code == 201, r.text
    lid = r.json()["id"]
    rs = await asyncio.gather(*[fc.post(f"/v1/my/listings/{lid}/publish", headers=A) for _ in range(5)])
    assert all(x.status_code in (200, 409) for x in rs), [x.text for x in rs]
    assert any(x.status_code == 200 for x in rs)
    assert len(await _rows(fc)) == 1
