import pytest

from ff_demand.config import Settings
from ff_demand.main import create_app


def test_production_requires_internal_token(monkeypatch):
    monkeypatch.setenv("FF_ENV", "production")
    monkeypatch.delenv("FF_INTERNAL_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="FF_INTERNAL_TOKEN"):
        create_app(Settings(_env_file=None))
    monkeypatch.setenv("FF_INTERNAL_TOKEN", "t")
    app = create_app(Settings(_env_file=None))
    from fastapi.testclient import TestClient

    c = TestClient(app, headers={"X-Internal-Token": "t"})
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(p).status_code == 404
