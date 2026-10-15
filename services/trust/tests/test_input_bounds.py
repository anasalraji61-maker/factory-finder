from fastapi.testclient import TestClient

from ff_trust.main import create_app


def _c():
    return TestClient(create_app())


def test_overlong_supplier_id_rejected():
    c = _c()
    assert c.get("/v1/trust/suppliers/" + "a" * 129).status_code == 422
    assert c.get("/v1/trust/suppliers/" + "a" * 129 + "/history").status_code == 422


def test_batch_bounds():
    c = _c()
    assert c.get("/v1/trust/suppliers:batch?ids=" + "a" * 9000).status_code == 422
    assert c.get("/v1/trust/suppliers:batch?ids=" + "a" * 129).status_code == 422
    assert c.get("/v1/trust/suppliers:batch?ids=,,").status_code == 422
    r = c.get("/v1/trust/suppliers:batch?ids=" + ",".join(f"s{i}" for i in range(51)))
    assert r.json()["error"]["code"] == "too_many_ids"


def test_evaluate_list_and_number_bounds():
    c = _c()
    assert c.post("/v1/trust/evaluate", json={"certifications": ["x"] * 201}).status_code == 422
    assert c.post("/v1/trust/evaluate", json={"certifications": ["x" * 65]}).status_code == 422
    assert c.post("/v1/trust/evaluate", json={"certification_records": [{"name": "a"}] * 201}).status_code == 422
    r = c.post("/v1/trust/evaluate", content='{"years_in_business":NaN}', headers={"content-type": "application/json"})
    assert r.status_code == 422
