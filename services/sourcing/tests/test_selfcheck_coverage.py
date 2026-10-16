"""Selfcheck CLI guards + per-adapter mapping coverage against SYNTHETIC fixtures (mock HTTP transport only)."""

import json
from pathlib import Path

import httpx
import pytest

from ff_sourcing.adapters.alibaba_openapi import ACCESS_TOKEN_ENV, APP_KEY_ENV, APP_SECRET_ENV
from ff_sourcing.adapters.selfcheck import (
    ADAPTER_IDS,
    CONFIRM_ENV,
    REQUIRED,
    make_adapter,
    missing_fields,
    run_selfcheck,
)
from ff_sourcing.config import Settings
from ff_sourcing.domain.models import SearchQuery

FIX = Path(__file__).parent / "fixtures"
SECRET = "super-secret-value"
SETTINGS = Settings(
    alibaba_app_key="k", alibaba_app_secret=SECRET,
    aliexpress_app_key="k", aliexpress_app_secret=SECRET, aliexpress_tracking_id="t",
    s1688_app_key="k", s1688_app_secret=SECRET,
    mic_api_base="https://feed.example.invalid", mic_api_key=SECRET,
)
ENV = {
    APP_KEY_ENV: "k", APP_SECRET_ENV: SECRET, ACCESS_TOKEN_ENV: "tok-" + SECRET,
    CONFIRM_ENV: "1",
}
FIXTURE = {
    "alibaba": "alibaba_legacy_search.json",
    "alibaba_openapi": "alibaba_openapi_search.json",
    "aliexpress": "aliexpress_affiliate_query.json",
    "made_in_china": "mic_feed_search.json",
    "source_1688": "s1688_search.json",
}
# Required Listing fields that at least one fixture item (incl. deliberate edge records) does not
# supply, flagged explicitly and reviewed by hand. A mapping change that adds or drops a flag fails here.
# title/price/currency are never allowed to be missing: such items are dropped by the adapters.
EXPECTED_MISSING: dict[str, set[str]] = {
    "alibaba": {"moq"},
    "alibaba_openapi": {"images", "url"},
    "aliexpress": {"images", "supplier_id", "supplier_name", "url"},  # anonymous-shop edge record
    "made_in_china": {"images", "moq", "url"},
    "source_1688": {"images", "moq", "url"},
}


def _client(adapter_id, calls):
    payload = json.loads((FIX / FIXTURE[adapter_id]).read_text())

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_every_real_adapter_has_a_fixture():
    assert set(FIXTURE) == set(ADAPTER_IDS)


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
async def test_mapping_coverage(adapter_id):
    calls: list = []
    a = make_adapter(adapter_id, SETTINGS, ENV, _client(adapter_id, calls))
    items = await a.search(SearchQuery(q="x", keywords_en=["x"], limit=5))
    assert items
    union: set[str] = set()
    for it in items:
        miss = missing_fields(it)
        assert not miss & {"title", "price", "currency"}, (adapter_id, it.id, miss)
        union |= miss
    # every required field is either produced by at least one fixture item or explicitly flagged
    assert union <= set(REQUIRED)
    assert union == EXPECTED_MISSING[adapter_id], (adapter_id, union)
    # and at least one fixture item is fully populated for every required field
    assert any(not missing_fields(it) for it in items), adapter_id


@pytest.mark.parametrize("adapter_id", ADAPTER_IDS)
async def test_selfcheck_report_one_call_no_secrets(adapter_id):
    calls: list = []
    out: list[str] = []
    rc = await run_selfcheck(adapter_id, settings=SETTINGS, env=ENV, client=_client(adapter_id, calls), out=out.append)
    text = "\n".join(out)
    assert rc == 0 and len(calls) == 1, text
    assert "selfcheck " + adapter_id in text and "title" in text and "images" in text
    assert SECRET not in text and "tok-" not in text


async def test_selfcheck_refuses_without_confirm_or_when_killed_or_unconfigured():
    calls: list = []
    c = _client("aliexpress", calls)
    for env, word in (
        ({k: v for k, v in ENV.items() if k != CONFIRM_ENV}, "refused"),
        ({**ENV, "FF_SOURCING_KILL_SWITCH": "1"}, "kill switch"),
        ({**ENV, "FF_SOURCING_ALIEXPRESS_DISABLED": "true"}, "kill switch"),
    ):
        out: list[str] = []
        assert await run_selfcheck("aliexpress", settings=SETTINGS, env=env, client=c, out=out.append) == 2
        assert word in out[0]
    out = []
    assert await run_selfcheck("aliexpress", settings=Settings(), env=ENV, client=c, out=out.append) == 2
    assert "not configured" in out[0]
    assert await run_selfcheck("nope", env=ENV, out=out.append) == 2
    assert calls == []  # nothing was ever sent


async def test_selfcheck_failure_is_scrubbed_and_nonzero():
    def boom(req):
        return httpx.Response(403, text=SECRET)

    out: list[str] = []
    c = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    rc = await run_selfcheck("aliexpress", settings=SETTINGS, env=ENV, client=c, out=out.append)
    assert rc == 1 and "SourceBlocked" in out[0] and SECRET not in out[0]
