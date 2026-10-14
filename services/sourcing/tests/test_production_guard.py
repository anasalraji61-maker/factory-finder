import pytest

from ff_sourcing.config import Settings
from ff_sourcing.main import create_app


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
