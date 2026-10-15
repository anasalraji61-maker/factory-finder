"""QA round 3: the safety defaults themselves are pinned (a loosened default must fail a test)."""

import pytest
from pydantic import ValidationError

from ff_demand.config import Settings


def test_safe_defaults(monkeypatch):
    for k in ("FF_DEMAND_ENABLED", "FF_DEMAND_DAILY_CAP", "FF_DEMAND_PUBLISHER_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.enabled is False  # human-in-the-loop / kill switch OFF
    assert s.publisher_enabled is False
    assert 0 < s.daily_cap <= 20  # low daily volume


def test_cap_cannot_be_negative_and_host_interval_floor():
    with pytest.raises(ValidationError):
        Settings(daily_cap=-1)
    with pytest.raises(ValidationError):
        Settings(min_host_interval_seconds=1.0)
