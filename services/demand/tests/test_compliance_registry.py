"""CLAUDE.md rules 6-7 for the demand service, asserted by introspecting its adapters.

Introspected: every publisher class in ``ff_demand.publisher``, every signal source class in
``ff_demand.signals``, every HTTP route, and every source module. A new publisher that can send
without a named human + approved unedited draft, a new route that looks like private messaging, a
new module that opens its own network connection, or a real source without the polite client's
guards fails here. No network.
"""

# ruff: noqa: E501
from __future__ import annotations

import ast
import asyncio
import inspect
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import ff_demand
import ff_demand.publisher as publisher_mod
import ff_demand.signals as signals_mod
from ff_demand.compliance import AUTOMATED_ACTORS
from ff_demand.config import Settings
from ff_demand.errors import ApiError, Forbidden
from ff_demand.main import create_app
from ff_demand.polite import MIN_INTERVAL, PoliteClient, SourcePolicy
from ff_demand.publisher import text_sha
from ff_demand.signals import MockSignalSource, RawSignal
from ff_demand.sourcing import MockSourcingClient

H = {"X-User-Id": "admin1"}
AR = "أحتاج مكائن تعبئة من الصين"
SRC = Path(ff_demand.__file__).parent
TOKEN = "zz-sentinel-token-0042"


def _classes(mod, method: str):
    return [
        c
        for _, c in inspect.getmembers(mod, inspect.isclass)
        if c.__module__ == mod.__name__ and not getattr(c, "_is_protocol", False) and callable(getattr(c, method, None))
    ]


PUBLISHERS = _classes(publisher_mod, "publish")
SOURCES = _classes(signals_mod, "fetch")


def make(enabled=True, cap=20, **kw):
    mock = MockSourcingClient()
    return create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:", enabled=enabled, daily_cap=cap, **kw),
        sourcing=mock,
        source=MockSignalSource(),
    )


def approved_draft(text="reply"):
    return {
        "id": "d1", "status": "approved", "text": text, "approved_by": "admin1",
        "approved_at": datetime.now(UTC).isoformat(), "approved_text_sha": text_sha(text),
    }  # fmt: skip


# ---- inventory sanity -------------------------------------------------------------------------
def test_introspection_finds_adapters():
    assert {c.__name__ for c in PUBLISHERS} >= {"MockPublisher", "RealPublisher"}
    assert {c.__name__ for c in SOURCES} >= {"MockSignalSource"}


# ---- defaults: everything real is OFF, volume low -----------------------------------------------
def test_safe_defaults(monkeypatch):
    for k in ("FF_DEMAND_ENABLED", "FF_DEMAND_PUBLISHER_ENABLED", "FF_DEMAND_DAILY_CAP", "FF_DEMAND_SIGNAL_SOURCE"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.enabled is False and s.publisher_enabled is False
    assert 0 < s.daily_cap <= 20
    assert s.signal_source == "mock"
    assert s.min_host_interval_seconds >= 3.0 and MIN_INTERVAL >= 3.0


def test_default_app_wires_only_a_disabled_real_publisher_and_mock_source():
    app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:"), sourcing=MockSourcingClient())
    svc = app.state.service
    assert type(svc.publisher).__name__ == "RealPublisher" and svc.publisher.enabled is False
    assert isinstance(svc.source, MockSignalSource)


def test_floor_and_honest_user_agent_are_enforced_in_config():
    with pytest.raises(ValidationError):
        Settings(min_host_interval_seconds=1.0)
    for ua in ("Mozilla/5.0 Chrome/120", "", "Googlebot/2.1", "curl/8"):
        with pytest.raises(ValidationError):
            Settings(user_agent=ua)
    assert "bot" in Settings().user_agent.lower()


# ---- rule 7: publishers never send privately, never without a human + approval -------------------
@pytest.mark.parametrize("cls", PUBLISHERS, ids=lambda c: c.__name__)
async def test_publisher_refuses_unapproved_and_automated(cls):
    p = cls()
    for bad in ({"id": "d", "status": "draft", "text": "x"}, {**approved_draft(), "text": "tampered"}):
        with pytest.raises(ApiError):
            await p.publish(bad, "admin1")
    for actor in AUTOMATED_ACTORS:
        with pytest.raises(ApiError):
            await p.publish(approved_draft(), actor)
    no_human = {**approved_draft(), "approved_by": "system"}
    with pytest.raises(ApiError):
        await p.publish(no_human, "admin1")


async def test_real_publisher_is_off_by_default_and_never_sends_even_when_enabled():
    with pytest.raises(Forbidden):
        await publisher_mod.RealPublisher().publish(approved_draft(), "admin1")
    with pytest.raises(NotImplementedError):  # no channel wired: nothing can be sent
        await publisher_mod.RealPublisher(enabled=True).publish(approved_draft(), "admin1")


def test_no_private_message_surface():
    bad = re.compile(r"(?i)\b(dm|dms|private|direct[_ ]?message|whisper|inbox|whatsapp|telegram|sms|email|send[_-]?message|messenger)\b|(?:^|[_/-])(dm|pm)(?:$|[_/-])")
    app = make()
    for r in app.routes:
        assert not bad.search(getattr(r, "path", "")), f"route looks like private messaging: {r.path}"
    for cls in (*PUBLISHERS, type(app.state.service)):
        for name, _ in inspect.getmembers(cls, callable):
            assert not bad.search(name), f"{cls.__name__}.{name} looks like private messaging"


def test_only_audited_modules_touch_the_network():
    allowed = {"sourcing.py", "polite.py"}  # sourcing: our own service; polite: robots-aware reader
    banned = {"httpx", "requests", "aiohttp", "smtplib", "socket", "urllib3", "websockets", "telnetlib", "ftplib", "imaplib", "poplib"}
    for f in SRC.glob("*.py"):
        if f.name in allowed:
            continue
        mods = set()
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                mods.add(n.module.split(".")[0])
        assert not mods & banned, f"{f.name} imports a network library: {mods & banned}"


def test_polling_never_publishes_or_approves():
    class Spy:
        calls = 0

        async def publish(self, draft, actor):
            Spy.calls += 1
            return "u"

    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:", enabled=True, publisher_enabled=True),
        sourcing=MockSourcingClient(), source=MockSignalSource(), publisher=Spy(),
    )  # fmt: skip
    with TestClient(app) as c:
        assert c.post("/v1/signals/poll", headers=H).status_code == 200
        drafts = c.get("/v1/drafts", headers=H).json()
        items = drafts["items"] if isinstance(drafts, dict) else drafts
        assert items and all(d["status"] == "draft" for d in items)
    assert Spy.calls == 0


# ---- human approval switch ------------------------------------------------------------------------
def test_approval_needs_switch_on_and_a_named_human():
    off = make(enabled=False)
    with TestClient(off) as c:
        did = c.post("/v1/signals", headers=H, json={"text": AR}).json()["draft"]["id"]
        assert c.post(f"/v1/drafts/{did}/approve", headers=H, json={}).status_code == 403
        assert c.post(f"/v1/drafts/{did}/mark-published", headers=H, json={}).status_code == 403
    on = make(enabled=True)
    with TestClient(on) as c:
        did = c.post("/v1/signals", headers=H, json={"text": AR}).json()["draft"]["id"]
        for actor in AUTOMATED_ACTORS:
            r = c.post(f"/v1/drafts/{did}/approve", headers={"X-User-Id": actor}, json={})
            assert r.status_code >= 400, actor
        assert c.get(f"/v1/drafts/{did}", headers=H).json()["status"] == "draft"
        assert c.post(f"/v1/drafts/{did}/mark-published", headers=H, json={}).status_code >= 400  # unapproved
        assert c.post(f"/v1/drafts/{did}/approve", headers=H, json={}).status_code == 200


@pytest.mark.parametrize("cap", [0, 1, 2])
def test_daily_cap_is_a_hard_limit(cap):
    texts = [AR, "Looking for filling machines from China, small factory", "need centrifugal pump"]
    with TestClient(make(cap=cap)) as c:
        ids = [c.post("/v1/signals", headers=H, json={"text": t}).json()["draft"]["id"] for t in texts]
        codes = [c.post(f"/v1/drafts/{i}/approve", headers=H, json={}).status_code for i in ids]
    assert codes.count(200) == cap
    assert all(x == 429 for x in codes if x != 200)


def test_publish_via_adapter_needs_switch_adapter_and_approved_draft():
    pub = publisher_mod.MockPublisher()
    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:", enabled=True),
        sourcing=MockSourcingClient(), source=MockSignalSource(), publisher=pub,
    )  # fmt: skip
    svc = app.state.service
    with TestClient(app) as c:
        call = c.portal.call
        did = c.post("/v1/signals", headers=H, json={"text": AR}).json()["draft"]["id"]
        with pytest.raises(ApiError):  # not approved yet
            call(svc.publish_via_adapter, did, "admin1")
        assert c.post(f"/v1/drafts/{did}/approve", headers=H, json={}).status_code == 200
        with pytest.raises(ApiError):  # automated actor
            call(svc.publish_via_adapter, did, "system")
        svc.settings.enabled = False
        with pytest.raises(ApiError):  # kill switch off
            call(svc.publish_via_adapter, did, "admin1")
        svc.settings.enabled = True
        svc.publisher = None
        with pytest.raises(ApiError):  # no adapter configured
            call(svc.publish_via_adapter, did, "admin1")
        assert pub.published == []
        svc.publisher = pub
        assert call(svc.publish_via_adapter, did, "admin1")["status"] == "published"
        with pytest.raises(ApiError):  # never sent twice
            call(svc.publish_via_adapter, did, "admin1")
        assert len(pub.published) == 1


# ---- rule 6: signal sources ---------------------------------------------------------------------------
@pytest.mark.parametrize("cls", SOURCES, ids=lambda c: c.__name__)
async def test_signal_sources_are_deterministic_offline_and_typed(cls):
    out = await asyncio.wait_for(cls().fetch(), 5)
    assert out and all(isinstance(r, RawSignal) and not r.scraping_disallowed for r in out)
    assert all((r.url or "").startswith("https://example.test") for r in out), "fixture source must not point at real hosts"


def test_disallowed_sources_are_never_ingested():
    class Src:
        async def fetch(self):
            return [
                RawSignal(AR, "https://x.test/1", source="fb", scraping_disallowed=True),
                RawSignal(AR + " 2", "https://x.test/2", source="blockedsite"),
            ]

    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:", blocked_sources="blockedsite"),
        sourcing=MockSourcingClient(), source=Src(),
    )  # fmt: skip
    with TestClient(app) as c:
        assert c.post("/v1/signals/poll", headers=H).status_code == 200
        drafts = c.get("/v1/drafts", headers=H).json()
        assert (drafts["items"] if isinstance(drafts, dict) else drafts) == []


# ---- PoliteClient: the only sanctioned reader of public pages -------------------------------------------
class Net:
    def __init__(self, robots="User-agent: *\nAllow: /"):
        self.requests: list[httpx.Request] = []
        self.robots = robots

    def __call__(self, request):
        self.requests.append(request)
        if request.url.path == "/robots.txt":
            if isinstance(self.robots, Exception):
                raise self.robots
            if isinstance(self.robots, int):
                return httpx.Response(self.robots)
            return httpx.Response(200, text=self.robots)
        if request.url.path == "/redir":
            return httpx.Response(302, headers={"location": "https://login.test/"})
        return httpx.Response(200, text="ok")

    def polite(self, policy="ok", **kw):
        if policy == "ok":
            policy = SourcePolicy("pub", automated_access_allowed=True)
        self.t = {"v": 0.0}
        self.slept: list[float] = []

        async def sleep(d):
            self.slept.append(d)
            self.t["v"] += d

        return PoliteClient(
            policy, "FactoryFinderBot/0.1 (+https://x.test)",
            client=httpx.AsyncClient(transport=httpx.MockTransport(self)),
            clock=lambda: self.t["v"], sleep=sleep, **kw,
        )  # fmt: skip


def test_polite_client_demands_honest_ua_and_floors_interval():
    net = Net()
    for ua in ("", "Mozilla/5.0 Chrome", "Googlebot/2.1 bot"):
        with pytest.raises(ValueError):
            PoliteClient(None, ua, client=httpx.AsyncClient())
    assert net.polite(min_interval=0.0).min_interval >= 3.0


async def test_polite_client_default_policy_is_deny():
    net = Net()
    for pol in (None, SourcePolicy("x"), SourcePolicy("x", True, robots_disallowed=True)):
        with pytest.raises(Forbidden):
            await net.polite(pol).get("https://a.test/p")
    assert net.requests == []


@pytest.mark.parametrize("robots", ["User-agent: *\nDisallow: /", 401, 403, 429, 500, 301, httpx.ConnectError("x")],
                         ids=["disallow", "401", "403", "429", "500", "3xx", "network"])
async def test_polite_client_robots_fail_closed(robots):
    net = Net(robots)
    with pytest.raises(Forbidden):
        await net.polite().get("https://a.test/p")
    assert [r.url.path for r in net.requests] == ["/robots.txt"]


async def test_polite_client_spacing_ua_robots_cache_and_no_redirects():
    net = Net()
    p = net.polite()
    await p.get("https://a.test/1")
    await p.get("https://a.test/2")
    assert sum(r.url.path == "/robots.txt" for r in net.requests) == 1
    assert all("bot" in r.headers["user-agent"].lower() for r in net.requests)
    assert net.slept and all(d >= 3.0 - 1e-9 for d in net.slept)
    r = await p.get("https://a.test/redir")
    assert r.status_code == 302 and not any(x.url.host == "login.test" for x in net.requests)


# ---- no secrets in logs / reprs ------------------------------------------------------------------------------
def test_internal_token_never_logged_or_repr(caplog, capfd):
    caplog.set_level(logging.DEBUG)
    s = Settings(database_url="sqlite+aiosqlite:///:memory:", enabled=True, internal_token=TOKEN)
    app = create_app(s, sourcing=MockSourcingClient(), source=MockSignalSource())
    with TestClient(app) as c:
        h = {**H, "X-Internal-Token": TOKEN}
        c.post("/v1/signals", headers=h, json={"text": AR})
        c.get("/v1/quota", headers=h)
        c.get("/v1/quota", headers={**H, "X-Internal-Token": "wrong"})
    out = capfd.readouterr()
    assert TOKEN not in repr(s) + str(s) + caplog.text + out.out + out.err
