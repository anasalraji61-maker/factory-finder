"""Bundled directory is unverified: suggestions must never claim high confidence."""
from ff_tracking.domain.directory import load_directory, suggest_carrier
from ff_tracking.domain.enums import ReferenceType


def test_suggestions_never_high_confidence():
    d = load_directory()
    for o in d.ocean:
        for p in o.get("container_prefixes", ()):
            s = suggest_carrier(ReferenceType.CONTAINER, p)
            assert s is None or s.confidence in {"medium", "low"}
    for a in d.airlines:
        s = suggest_carrier(ReferenceType.AWB, a["awb_prefix"])
        assert s is not None and s.confidence in {"medium", "low"}
