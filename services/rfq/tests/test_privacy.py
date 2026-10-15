import pytest
from conftest import BUYER, SUP_A, new_offer, new_request
from fastapi.testclient import TestClient

from ff_rfq.config import Settings
from ff_rfq.main import create_app

TOK = {"X-Internal-Token": "s3cret"}


@pytest.fixture
def c(clock):
    s = Settings(database_url="sqlite+aiosqlite:///:memory:", sourcing_client="mock", internal_token="s3cret")
    with TestClient(create_app(s, clock=clock), headers=TOK) as client:
        yield client


def test_non_internal_gets_404(c):
    assert c.post("/v1/internal/users/buyer1/export", headers={"X-Internal-Token": "bad"}).status_code == 404
    assert c.delete("/v1/internal/users/buyer1/data", headers={"X-Internal-Token": ""}).status_code == 404


def test_erase_scrubs_text_keeps_deal_records(c):
    deal_req = new_request(c, title="private secret title")
    off = new_offer(c, deal_req["id"], SUP_A, notes="call me on my phone")
    deal = c.post(f"/v1/offers/{off['id']}/accept", headers=BUYER).json()
    lone = new_request(c, title="another personal need", description="my home address")
    exp = c.post("/v1/internal/users/buyer1/export").json()
    assert exp["service"] == "rfq" and len(exp["data"]["requests"]) == 2 and len(exp["data"]["deals"]) == 1
    d = c.delete("/v1/internal/users/buyer1/data").json()
    assert d["status"] == "done" and d["counts"]["requests_scrubbed"] == 1 and "deals" in d["retained"]
    again = c.delete("/v1/internal/users/buyer1/data").json()
    assert again["counts"]["requests_scrubbed"] == 1  # same row set re-scrubbed: idempotent, no new effect
    got = c.get(f"/v1/requests/{lone['id']}", headers=BUYER).json()
    assert got["title"] == "[deleted]" and got["status"] == "cancelled" and not got.get("description")
    assert c.get(f"/v1/requests/{deal_req['id']}", headers=BUYER).json()["title"] == "private secret title"
    assert c.get(f"/v1/deals/{deal['id']}", headers=BUYER).status_code == 200  # financial record kept
    assert c.post("/v1/internal/users/buyer1/export").json()["data"]["offers"] == []
    # supplier side: notes gone, accepted offer keeps its price
    sup = c.post("/v1/internal/users/supA/export").json()["data"]["offers"]
    assert sup[0]["notes"] == "call me on my phone"
    c.delete("/v1/internal/users/supA/data")
    sup = c.post("/v1/internal/users/supA/export").json()["data"]["offers"]
    assert sup[0]["notes"] is None and sup[0]["price_amount"] == "12.50"
