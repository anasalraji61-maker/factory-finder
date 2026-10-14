"""Licensed feed hardening: response size cap, hostile ids/urls/titles. No network."""

import asyncio
import json
from pathlib import Path

import httpx

from ff_sourcing.adapters import http_provider
from ff_sourcing.adapters.licensed_rest import LicensedRestAdapter, load_mapping
from ff_sourcing.domain.models import SearchQuery

ROOT = Path(__file__).parents[1]
BEARER = ROOT / "examples" / "licensed" / "example_fictional_bearer.mapping.json"
R1 = json.loads((Path(__file__).parent / "fixtures" / "licensed_examplia_response.json").read_text())
Q = SearchQuery(q="pp granules", keywords_en=["pp", "granules"], limit=50)


class _Clock:
    t = 1000.0

    def __call__(self):
        return self.t

    async def sleep(self, d):
        self.t += d


def adapter(path, handler):
    clock = _Clock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    a = LicensedRestAdapter(
        load_mapping(path), client=client, env={"FF_SOURCING_EXAMPLIA_API_KEY": "sekrit-key-123456"},
        clock=clock, sleep=clock.sleep,
    )
    return a, clock


def ok(payload):
    return lambda req: httpx.Response(200, json=payload)


def test_oversized_response_is_refused(monkeypatch):
    monkeypatch.setattr(http_provider, "MAX_RESPONSE_BYTES", 1000)
    a, _ = adapter(BEARER, lambda req: httpx.Response(200, content=b'{"x":"' + b"a" * 5000 + b'"}'))
    try:
        asyncio.run(a.search(Q))
    except ValueError as e:
        assert "larger than" in str(e)
    else:
        raise AssertionError("oversized response accepted")


def test_hostile_item_fields_are_neutralised():
    a, _ = adapter(BEARER, ok(R1))
    items = asyncio.run(a.search(Q))
    assert items
    raw_items = a.extract_items(R1)
    m = a.spec.fields
    base = dict(raw_items[0])

    def put(raw, target, value):
        # write `value` at the mapped (possibly dotted) path
        keys = m[target].split(".")
        d = raw
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

    import copy

    bad_id = copy.deepcopy(base)
    put(bad_id, "id", "../../etc/passwd")
    assert a.normalize_item(bad_id) is None
    js = copy.deepcopy(base)
    put(js, "url", "javascript:alert(1)")
    got = a.normalize_item(js)
    assert got is not None and got.source_url is None
    long = copy.deepcopy(base)
    put(long, "title", "x" * 100_000)
    assert len(a.normalize_item(long).title) <= 300
