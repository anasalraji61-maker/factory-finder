"""Security review 2026-10-i: parser input is untrusted supplier text; regex work must stay bounded."""

import time

from ff_sourcing.domain.pricing import MAX_PRICE_TEXT, parse_price_text


def test_price_parser_bounded_on_adversarial_input():
    for text in ("1" * 300_000, "1-" * 150_000, "1999 " * 60_000, "1 pcs " * 50_000, "/ " * 100_000):
        t = time.perf_counter()
        parse_price_text(text)
        assert time.perf_counter() - t < 1.0


def test_price_parser_still_parses_normal_text():
    assert MAX_PRICE_TEXT >= 300
    p = parse_price_text("US$1.20 - 100-499 pcs; US$1.00 500+ pcs")
    assert p.currency == "USD" and len(p.tiers) == 2
