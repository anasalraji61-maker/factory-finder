import pytest

from ff_media.config import Settings
from ff_media.main import create_app


def test_production_requires_internal_token(monkeypatch, tmp_path):
    monkeypatch.setenv("FF_ENV", "production")
    monkeypatch.delenv("FF_INTERNAL_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="FF_INTERNAL_TOKEN"):
        create_app(Settings(_env_file=None))
    monkeypatch.setenv("FF_INTERNAL_TOKEN", "t")
    monkeypatch.delenv("FF_MEDIA_SIGNING_KEY", raising=False)
    with pytest.raises(RuntimeError, match="FF_MEDIA_SIGNING_KEY"):
        create_app(Settings(_env_file=None))
    monkeypatch.setenv("FF_MEDIA_SIGNING_KEY", "k" * 32)
    create_app(Settings(_env_file=None))


def test_default_env_unchanged(monkeypatch):
    monkeypatch.delenv("FF_ENV", raising=False)
    monkeypatch.delenv("FF_INTERNAL_TOKEN", raising=False)
    create_app(Settings(_env_file=None))
