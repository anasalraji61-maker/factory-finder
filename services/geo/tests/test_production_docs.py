from fastapi.testclient import TestClient

from ff_geo.main import create_app


def test_production_hides_docs(monkeypatch):
    monkeypatch.setenv("FF_ENV", "production")
    c = TestClient(create_app())
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(p).status_code == 404
    assert c.get("/health").status_code == 200
