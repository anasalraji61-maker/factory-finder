import pytest

from ff_rfq.config import Settings
from ff_rfq.main import create_app


def test_production_requires_internal_token(monkeypatch, tmp_path):
    monkeypatch.setenv("FF_ENV", "production")
    monkeypatch.delenv("FF_INTERNAL_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="FF_INTERNAL_TOKEN"):
        create_app(Settings(_env_file=None))
    monkeypatch.setenv("FF_INTERNAL_TOKEN", "t")
    create_app(Settings(_env_file=None))


def test_default_env_unchanged(monkeypatch):
    monkeypatch.delenv("FF_ENV", raising=False)
    monkeypatch.delenv("FF_INTERNAL_TOKEN", raising=False)
    create_app(Settings(_env_file=None))


def test_production_warns_when_single_invoice_settles(monkeypatch, caplog):
    import logging

    from ff_rfq.config import Settings
    from ff_rfq.main import create_app
    monkeypatch.setenv("FF_ENV", "production")
    monkeypatch.setenv("FF_INTERNAL_TOKEN", "t")
    def mk(**kw):
        return Settings(database_url="sqlite+aiosqlite:///:memory:", sourcing_client="mock", **kw)

    with caplog.at_level(logging.WARNING, logger="ff_rfq"):
        create_app(mk())
    assert "REQUIRE_BOTH_INVOICES" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="ff_rfq"):
        create_app(mk(require_both_invoices=True))
    assert "REQUIRE_BOTH_INVOICES" not in caplog.text
