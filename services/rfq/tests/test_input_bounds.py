"""QA: oversized / hostile inputs must be 4xx, never 500."""

from conftest import BUYER, SUP_A, new_request
from starlette.testclient import TestClient


def _c(client):
    return TestClient(client.app, raise_server_exceptions=False)


def test_huge_page_is_422_not_500(client):
    c = _c(client)
    for p in ("99999999999999999999", "9223372036854775807", "100001"):
        assert c.get(f"/v1/requests?page={p}", headers=BUYER).status_code == 422


def test_huge_moq_and_long_attachment_rejected(client):
    c = _c(client)
    r = new_request(client)
    body = {"price": {"amount": "1", "currency": "USD"}, "supplier_name": "x", "moq": 10**30}
    assert c.post(f"/v1/requests/{r['id']}/offers", json=body, headers=SUP_A).status_code == 422
    body = {"kind": "product", "title": "abcd", "quantity": "1", "attachments": ["a" * 501]}
    assert c.post("/v1/requests", json=body, headers=BUYER).status_code == 422


def test_hostile_user_id_header_rejected(client):
    c = _c(client)
    for bad in ("u" * 129, "a b", "x/../y", "ü"):
        try:
            r = c.get("/v1/requests", headers={"X-User-Id": bad})
        except Exception:  # header not encodable by the client: nothing to test
            continue
        assert r.status_code == 401, bad
