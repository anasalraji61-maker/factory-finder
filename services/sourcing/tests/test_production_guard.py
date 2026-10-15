import pytest

from ff_sourcing.config import Settings
from ff_sourcing.main import create_app


def test_production_requires_internal_token(monkeypatch, tmp_path):
    monkeypatch.setenv("FF_ENV", "production")
    monkeypatch.delenv("FF_INTERNAL_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="FF_INTERNAL_TOKEN"):
        create_app(Settings(_env_file=None))
    monkeypatch.setenv("FF_INTERNAL_TOKEN", "t")
    create_app(Settings(_env_file=None, reporter_hash_key="r" * 32, analytics_hash_key="a" * 32))


def test_default_env_unchanged(monkeypatch):
    monkeypatch.delenv("FF_ENV", raising=False)
    monkeypatch.delenv("FF_INTERNAL_TOKEN", raising=False)
    create_app(Settings(_env_file=None))


def test_production_requires_hash_keys(monkeypatch):
    monkeypatch.setenv("FF_ENV", "production")
    monkeypatch.setenv("FF_INTERNAL_TOKEN", "t")
    with pytest.raises(RuntimeError, match="REPORTER_HASH_KEY"):
        create_app(Settings(_env_file=None))
    with pytest.raises(RuntimeError, match="ANALYTICS_HASH_KEY"):
        create_app(Settings(_env_file=None, reporter_hash_key="r" * 32))
    app = create_app(Settings(_env_file=None, reporter_hash_key="r" * 32, analytics_hash_key="a" * 32))
    from fastapi.testclient import TestClient

    c = TestClient(app, headers={"X-Internal-Token": "t"})
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(p).status_code == 404
