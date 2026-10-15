"""CLAUDE.md rule 6, asserted by introspecting the adapter registry.

Every adapter that is not the deterministic mock / our own native store is "real" and must be:
off by default, behind a kill switch (global + its own), robots.txt fail-closed for page reads,
>= 3 s per host, honestly identified, cached, never bypassing CAPTCHA/login/paywall/redirects,
and must never leak credentials into errors or logs. A newly registered adapter that does not
inherit one of the guarded bases (or lacks a kill switch) fails here. Network is mocked.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from ff_sourcing.adapters.http_base import (
    MIN_INTERVAL_FLOOR_S,
    ApiSourceAdapter,
    HttpRequestSpec,
    RobotsGuard,
    SourceBlocked,
    SourceDisabled,
)
from ff_sourcing.adapters.http_provider import (
    HttpProviderAdapter,
    ProviderConfig,
    ProviderDisabled,
)
from ff_sourcing.adapters.registry import build_registry
from ff_sourcing.config import Settings
from ff_sourcing.domain.models import SearchQuery

SECRET = "zz-sentinel-secret-0042"
EXAMPLES = ",".join(str(p) for p in sorted((Path(__file__).parent.parent / "examples" / "licensed").glob("*.json")))
NON_REAL = {"mock", "native"}
BUILTIN_REAL = {"alibaba", "alibaba_openapi", "made_in_china", "aliexpress", "source_1688"}
MIC_BASE = "https://mic.test/api"


def _settings(**kw) -> Settings:
    base = dict(
        alibaba_app_key="k", alibaba_app_secret=SECRET, aliexpress_app_key="k",
        aliexpress_app_secret=SECRET, aliexpress_tracking_id="t", s1688_app_key="k",
        s1688_app_secret=SECRET, mic_api_base=MIC_BASE, mic_api_key=SECRET,
        licensed_mappings=EXAMPLES, licensed_allow_example=True,
    )  # fmt: skip
    return Settings(**{**base, **kw})


def _ids() -> list[str]:
    return sorted(a.id for a in build_registry(_settings()).all() if a.id not in NON_REAL)


@pytest.fixture(autouse=True)
def _creds(monkeypatch):
    """Provide env credentials for every provider-style adapter (env-only secrets)."""
    for name in ("FF_SOURCING_KILL_SWITCH",):
        monkeypatch.delenv(name, raising=False)
    for a in build_registry(_settings()).all():
        if isinstance(a, HttpProviderAdapter):
            if a.config.api_key_env:
                monkeypatch.setenv(a.config.api_key_env, SECRET)
            if a.config.kill_switch_env:
                monkeypatch.delenv(a.config.kill_switch_env, raising=False)
        if isinstance(a, ApiSourceAdapter):
            monkeypatch.delenv(f"FF_SOURCING_{a.id.upper()}_DISABLED", raising=False)
    for n in ("APP_KEY", "APP_SECRET", "ACCESS_TOKEN"):
        monkeypatch.setenv(f"FF_SOURCING_ALIBABA_{n}", SECRET)


class Net:
    """MockTransport recorder: every request an adapter makes lands in .requests."""

    def __init__(self, handler=None, robots: str | int | Exception = "User-agent: *\nAllow: /"):
        self.requests: list[httpx.Request] = []
        self.robots, self.handler = robots, handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/robots.txt":
            if isinstance(self.robots, Exception):
                raise self.robots
            if isinstance(self.robots, int):
                return httpx.Response(self.robots)
            return httpx.Response(200, text=self.robots)
        if self.handler:
            return self.handler(request)
        return httpx.Response(200, json={})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))

    @property
    def pages(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path != "/robots.txt"]


def adapter(aid: str, net: Net, settings: Settings | None = None, slept: list[float] | None = None):
    a = build_registry(settings or _settings()).get(aid)
    assert a is not None
    a._client = net.client()  # type: ignore[attr-defined]
    clock = {"t": 0.0}

    async def sleep(d: float) -> None:
        if slept is not None:
            slept.append(d)
        clock["t"] += d

    a.limiter._clock, a.limiter._sleep = lambda: clock["t"], sleep  # type: ignore[attr-defined]
    return a


def q(text: str = "bolt") -> SearchQuery:
    return SearchQuery(q=text, keywords_en=[text])


DISABLED = (SourceDisabled, ProviderDisabled)


def test_registry_has_real_adapters_to_check():
    ids = _ids()
    assert set(ids) >= BUILTIN_REAL
    assert set(ids) - BUILTIN_REAL, "licensed example mappings were not loaded"


@pytest.mark.parametrize("aid", _ids())
def test_adapter_uses_a_guarded_base_and_declares_compliance(aid):
    a = build_registry(_settings()).get(aid)
    assert isinstance(a, ApiSourceAdapter | HttpProviderAdapter), (
        f"{aid}: real adapters must inherit ApiSourceAdapter or HttpProviderAdapter "
        "(kill switch, robots, throttle, cache, honest UA)"
    )
    assert a.mode in ("official_api", "licensed_feed"), f"{aid}: mode {a.mode!r} is not lawful"
    assert a.compliance.strip(), f"{aid}: compliance statement missing"
    for secret_holder in (repr(a), str(a)):
        assert SECRET not in secret_holder


def test_all_real_adapters_off_by_default():
    assert Settings().enabled_set() == {"mock", "native"}
    for settings in (Settings(), _settings()):
        reg = build_registry(settings)
        for a in reg.all():
            if a.id not in NON_REAL:
                assert not reg.is_enabled(a.id), f"{a.id} is enabled by default"
        assert {a.id for a in reg.enabled()} <= NON_REAL


def test_real_adapters_only_enabled_by_explicit_opt_in():
    reg = build_registry(_settings(adapters="alibaba_openapi"))
    assert [a.id for a in reg.enabled() if a.id not in NON_REAL] == ["alibaba_openapi"]


def test_licensed_example_mappings_refused_unless_explicitly_allowed():
    ids = {a.id for a in build_registry(Settings(licensed_mappings=EXAMPLES)).all()}
    assert ids.isdisjoint(set(_ids()) - BUILTIN_REAL)


@pytest.mark.parametrize("aid", _ids())
def test_each_adapter_has_its_own_kill_switch(aid):
    a = build_registry(_settings()).get(aid)
    if isinstance(a, HttpProviderAdapter):
        assert a.config.kill_switch_env, f"{aid}: provider has no per-adapter kill switch env var"
    else:
        assert a.killed() is False


@pytest.mark.parametrize("aid", _ids())
@pytest.mark.parametrize("which", ["global", "own"])
async def test_kill_switch_stops_all_traffic(aid, which, monkeypatch):
    a = build_registry(_settings()).get(aid)
    if which == "global":
        name = "FF_SOURCING_KILL_SWITCH"
    elif isinstance(a, HttpProviderAdapter):
        name = a.config.kill_switch_env
    else:
        name = f"FF_SOURCING_{aid.upper()}_DISABLED"
    monkeypatch.setenv(name, "1")
    net = Net()
    a = adapter(aid, net)
    assert a.killed()
    with pytest.raises(DISABLED):
        await a.search(q())
    assert net.requests == []


@pytest.mark.parametrize("aid", _ids())
def test_throttle_floor_cannot_be_configured_away(aid):
    a = adapter(aid, Net(), _settings(min_request_interval_s=0.01))
    assert a.limiter.min_interval_s >= MIN_INTERVAL_FLOOR_S == 3.0
    cfg = ProviderConfig(id="x", name="x", base_url="https://x.test", min_interval_s=0.0)
    assert HttpProviderAdapter(cfg).limiter.min_interval_s >= 3.0


@pytest.mark.parametrize("aid", _ids())
async def test_requests_to_one_host_are_spaced_at_least_3s(aid):
    net, slept = Net(), []
    a = adapter(aid, net, slept=slept)
    await a.search(q("one"))
    await a.search(q("two"))  # different query: cache miss
    assert len(net.pages) >= 2
    assert len(slept) >= 1 and all(d >= 3.0 - 1e-9 for d in slept), slept


@pytest.mark.parametrize("aid", _ids())
async def test_user_agent_is_honest_on_every_request(aid):
    net = Net()
    a = adapter(aid, net)
    await a.search(q())
    assert net.requests
    for r in net.requests:
        ua = r.headers.get("user-agent", "")
        assert "bot" in ua.lower() and "factoryfinder" in ua.lower().replace(" ", ""), ua
        assert not any(w in ua.lower() for w in ("mozilla", "chrome", "safari", "googlebot"))


def test_user_agent_cannot_be_configured_to_impersonate():
    for ua in ("Mozilla/5.0 (Windows NT 10.0) Chrome/120", "", "Googlebot/2.1", "curl/8"):
        with pytest.raises(ValidationError):
            Settings(user_agent=ua)
        with pytest.raises(ValidationError):
            ProviderConfig(id="x", name="x", base_url="https://x.test", user_agent=ua)


@pytest.mark.parametrize("aid", _ids())
async def test_identical_searches_are_cached(aid):
    net = Net()
    a = adapter(aid, net)
    await a.search(q("same"))
    n = len(net.pages)
    assert n >= 1
    await a.search(q("same"))
    assert len(net.pages) == n, "second identical search hit the network"


@pytest.mark.parametrize("aid", _ids())
@pytest.mark.parametrize("status", [401, 403, 429])
async def test_refusals_are_never_retried_or_bypassed(aid, status):
    net = Net(handler=lambda r: httpx.Response(status, headers={"retry-after": "5"}))
    a = adapter(aid, net)
    with pytest.raises(SourceBlocked):
        await a.search(q())
    assert len(net.pages) == 1
    if status == 429:  # cooldown honoured: nothing further to this host
        with pytest.raises(SourceBlocked):
            await a.search(q("another"))
        assert len(net.pages) == 1


@pytest.mark.parametrize("aid", _ids())
async def test_captcha_page_stops_and_redirects_are_not_followed(aid):
    net = Net(handler=lambda r: httpx.Response(200, text="<html>please solve the captcha</html>"))
    a = adapter(aid, net)
    with pytest.raises(SourceBlocked):
        await a.search(q())
    assert len(net.pages) == 1
    net = Net(handler=lambda r: httpx.Response(302, headers={"location": "https://login.test/signin"}))
    a = adapter(aid, net)
    with pytest.raises(Exception):  # noqa: B017
        await a.search(q())
    assert [r.url.host for r in net.pages] != ["login.test"] and len(net.pages) == 1


API_ADAPTERS = [i for i in _ids() if isinstance(build_registry(_settings()).get(i), ApiSourceAdapter)]


@pytest.mark.parametrize("aid", API_ADAPTERS)
@pytest.mark.parametrize(
    "robots",
    ["User-agent: *\nDisallow: /", 401, 403, 429, 500, 503, 301, httpx.ConnectError("down")],
    ids=["disallow", "401", "403", "429", "500", "503", "3xx", "network"],
)
async def test_page_reads_fail_closed_on_robots(aid, robots):
    net = Net(robots=robots)
    a = adapter(aid, net)
    with pytest.raises(SourceBlocked):
        await a.fetch(HttpRequestSpec(url="https://pages.test/list", kind="page"))
    assert net.pages == []


@pytest.mark.parametrize("aid", API_ADAPTERS)
async def test_page_reads_allowed_when_robots_allows_and_robots_is_cached(aid):
    net = Net(robots="User-agent: *\nDisallow: /private")
    a = adapter(aid, net)
    await a.fetch(HttpRequestSpec(url="https://pages.test/list", kind="page"))
    await a.fetch(HttpRequestSpec(url="https://pages.test/list2", kind="page"))
    with pytest.raises(SourceBlocked):
        await a.fetch(HttpRequestSpec(url="https://pages.test/private/x", kind="page"))
    assert sum(r.url.path == "/robots.txt" for r in net.requests) == 1


async def test_robots_404_means_allowed_but_unreachable_means_closed():
    net = Net(robots=404)
    async with net.client() as c:
        assert await RobotsGuard("FactoryFinderBot/0.1", c).allowed("https://a.test/x")
    net = Net(robots=httpx.ReadTimeout("t"))
    async with net.client() as c:
        assert not await RobotsGuard("FactoryFinderBot/0.1", c).allowed("https://a.test/x")


async def test_public_page_mode_is_opt_in_and_robots_enforced():
    s = _settings(mic_api_key="", mic_allow_public_pages=True)
    net = Net(robots="User-agent: *\nDisallow: /")
    a = adapter("made_in_china", net, s)
    with pytest.raises(SourceBlocked):
        await a.search(q())
    assert net.pages == []
    s = _settings(mic_api_key="", mic_allow_public_pages=False)
    assert not adapter("made_in_china", Net(), s).configured()


@pytest.mark.parametrize("aid", _ids())
async def test_no_secret_in_errors_reprs_or_logs(aid, caplog):
    caplog.set_level(logging.DEBUG)
    net = Net(handler=lambda r: httpx.Response(500))
    s = _settings()
    a = adapter(aid, net, s)
    with pytest.raises(RuntimeError) as ei:
        await a.search(q())
    text = "\n".join([str(ei.value), repr(a), repr(s), str(s), caplog.text])
    assert SECRET not in text
