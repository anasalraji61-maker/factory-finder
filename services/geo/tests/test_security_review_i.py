"""Security review 2026-10-i: the fuzzy city search must stay cheap for adversarial queries up to the 100-char cap."""

import time

from ff_geo.domain.data import get_dataset
from ff_geo.domain.search import search_cities

ds = get_dataset()


def test_search_bounded_for_long_adversarial_queries():
    names = sorted((c.name_en for c in ds.cities), key=len, reverse=True)
    longest = names[0]
    queries = ["a" * 100, "ال" * 50, "x " * 50, "zzzz" + "a" * 96, longest + "q" * (100 - len(longest)), (longest + " ") * 5,
               "ab" * 8, "q" * 20, longest[:-1] + "x"]
    for q in queries:
        t = time.perf_counter()
        search_cities(ds, q[:100])
        assert time.perf_counter() - t < 1.0, q
