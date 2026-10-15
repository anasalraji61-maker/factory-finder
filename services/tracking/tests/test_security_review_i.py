"""Security review 2026-10-i: provider text is untrusted; regexes must not go quadratic on adversarial input."""

import time

from ff_tracking.domain import normalize as n
from ff_tracking.domain import validators as v


def _fast(fn, arg, limit=0.5):
    t = time.perf_counter()
    fn(arg)
    assert time.perf_counter() - t < limit


def test_parse_ts_whitespace_run_is_fast_and_still_handles_utc_suffix():
    _fast(n.parse_ts, "2026" + " " * 200_000 + "x")
    _fast(n.parse_ts, " " * 200_000 + "UTC")
    assert n.parse_ts("2026-03-01T10:00:00 UTC") == n.parse_ts("2026-03-01T10:00:00Z")
    assert n.parse_ts("2026-03-01T10:00:00   gmt") == n.parse_ts("2026-03-01T10:00:00Z")


def test_vessel_name_whitespace_run_is_fast():
    for s in ("A" + " " * 200_000 + "IM", "(" + " " * 200_000, "M" + " " * 200_000 + "/", "IMO " * 50_000):
        _fast(v.clean_vessel_name, s)
        _fast(v.parse_vessel, {"name": s, "imo": ""})
    assert v.parse_vessel({"name": "MSC GULSUN (IMO 9811000)"}).name == "MSC GULSUN"


def test_reference_validators_fast_at_length_cap():
    for fn in (v.validate_bl, v.validate_awb, v.validate_imo, v.validate_container):
        for s in (" " * 64, "-" * 64, "BL" + " " * 62, "1" * 64):
            _fast(fn, s, 0.05)
