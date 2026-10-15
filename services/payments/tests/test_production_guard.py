import pytest

from ff_payments.config import Settings
from ff_payments.main import create_app


def test_production_requires_internal_token(monkeypatch, tmp_path):
    monkeypatch.setenv("FF_ENV", "production")
    monkeypatch.delenv("FF_INTERNAL_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="FF_INTERNAL_TOKEN"):
        create_app(Settings(_env_file=None))
    monkeypatch.setenv("FF_INTERNAL_TOKEN", "t")
    with pytest.raises(RuntimeError, match="mock"):
        create_app(Settings(_env_file=None))
    with pytest.raises(RuntimeError, match="WEBHOOK_SECRET_USDT_TRON"):
        create_app(Settings(_env_file=None, provider="usdt_tron", admin_token="a"))
    with pytest.raises(RuntimeError, match="ADMIN_TOKEN"):
        create_app(Settings(_env_file=None, provider="usdt_tron", webhook_secret_usdt_tron="w"))
    create_app(Settings(_env_file=None, provider="usdt_tron", webhook_secret_usdt_tron="w", admin_token="a"))


def test_production_hides_docs(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("FF_ENV", "production")
    monkeypatch.setenv("FF_INTERNAL_TOKEN", "t")
    app = create_app(Settings(_env_file=None, provider="off", admin_token="a"))
    c = TestClient(app, headers={"X-Internal-Token": "t"})
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(p).status_code == 404


def test_default_env_unchanged(monkeypatch):
    monkeypatch.delenv("FF_ENV", raising=False)
    monkeypatch.delenv("FF_INTERNAL_TOKEN", raising=False)
    create_app(Settings(_env_file=None))
