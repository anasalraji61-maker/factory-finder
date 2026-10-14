import base64
import json

import pytest

from ff_feed import cursor as cur
from ff_feed.errors import Invalid


def _cur(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode()


@pytest.mark.parametrize("d", [
    {"k": "t", "t": "0001-01-01T00:00:00+05:00", "i": "a", "s": 1},
    {"k": "c", "t": "9999-12-31T23:59:59-05:00", "i": "a"},
    {"k": "t", "t": "2026-01-01T00:00:00+00:00", "i": "a", "s": 10**30},
])
def test_hostile_cursors_rejected(d):
    with pytest.raises(Invalid):
        cur.decode(_cur(d), ("t", "c"))


def test_email_screen_still_detects_and_is_not_quadratic():
    import time

    from ff_feed.moderation import contact_kinds, redact

    assert "contact_email" in contact_kinds("write to john.doe@example.com today")
    assert "contact_email" in contact_kinds("john[at]example[dot]com")
    assert redact("mail a.b+c@ex.org now") == "mail [redacted] now"
    t = time.perf_counter()
    for v in ("a" * 2200, "a." * 1100, "a.b." * 550 + "@"):
        contact_kinds(v)
    assert time.perf_counter() - t < 0.5  # was ~0.2 s per 2 kB input before the lookbehind anchor
