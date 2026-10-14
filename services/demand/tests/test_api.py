from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ff_demand.config import Settings
from ff_demand.intent import detect_language, extract_intent
from ff_demand.main import create_app
from ff_demand.signals import MockSignalSource
from ff_demand.sourcing import MockSourcingClient

H = {"X-User-Id": "admin1"}
AR = "أحتاج مكائن تعبئة من الصين"
EN = "Looking for filling machines from China, small factory"


class Env:
    def __init__(self, client, app, mock):
        self.c, self.svc, self.mock = client, app.state.service, mock
        self.now = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
        self.svc.clock = lambda: self.now

    def signal(self, text=AR, url=None, **kw):
        r = self.c.post("/v1/signals", headers=H, json={"text": text, "url": url, **kw})
        assert r.status_code in (200, 201), r.text
        return r.json()

    def draft(self, text=AR, url=None):
        d = self.signal(text, url)["draft"]
        assert d
        return d["id"]

    def act(self, did, action, **body):
        return self.c.post(f"/v1/drafts/{did}/{action}", headers=H, json=body)


def make(enabled=True, cap=20):
    mock = MockSourcingClient()
    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:", enabled=enabled, daily_cap=cap),
        sourcing=mock,
        source=MockSignalSource(),
    )
    return app, mock


@pytest.fixture
def env():
    app, mock = make()
    with TestClient(app) as c:
        yield Env(c, app, mock)


@pytest.fixture
def env_off():
    app, mock = make(enabled=False)
    with TestClient(app) as c:
        yield Env(c, app, mock)


@pytest.fixture
def env_cap2():
    app, mock = make(cap=2)
    with TestClient(app) as c:
        yield Env(c, app, mock)


def test_auth_required(env):
    assert env.c.get("/v1/drafts").status_code == 401


def test_kill_switch_defaults_off():
    assert Settings().enabled is False
    assert Settings().daily_cap == 20


def test_language_and_intent_rules():
    assert detect_language(AR) == "ar"
    assert detect_language(EN) == "en"
    assert detect_language(EN, "ar") == "ar"
    i = extract_intent(AR)
    assert i and i.query == "مكائن تعبئة" and i.origin_country == "CN"
    i = extract_intent(EN)
    assert i and i.query == "filling machines" and i.origin_country == "CN"
    assert extract_intent("بيع سيارة موديل 2019") is None


def test_arabic_draft_has_disclosure_and_no_promises(env):
    r = env.signal(AR)
    d = r["draft"]
    assert r["signal"]["status"] == "drafted" and r["signal"]["language"] == "ar"
    assert d["status"] == "draft" and d["language"] == "ar" and d["disclosure"] is True
    assert "منصة" in d["text"] and "تقريبية" in d["text"]
    assert d["listing_ids"] and d["approved_by"] is None


def test_english_draft_language(env):
    d = env.signal(EN)["draft"]
    assert d["language"] == "en" and "not an individual" in d["text"]
    assert "indicative" in d["text"]


def test_dedupe_same_text_and_url(env):
    a = env.signal(AR)
    b = env.signal("  " + AR.upper() + " ")
    assert b["duplicate"] is True and b["signal"]["id"] == a["signal"]["id"]
    assert b["draft"]["id"] == a["draft"]["id"]
    u1 = env.signal("need pumps", "https://x.test/p/9")
    u2 = env.signal("totally different text", "https://x.test/p/9/")
    assert u2["duplicate"] and u2["signal"]["id"] == u1["signal"]["id"]
    assert env.c.get("/v1/drafts", headers=H).json()["total"] == 2


def test_not_a_buy_request_and_no_match(env):
    s = env.signal("بيع سيارة موديل 2019")
    assert s["signal"]["status"] == "ignored" and s["draft"] is None
    s = env.signal("أحتاج طائرات مسيرة")
    assert s["signal"]["status"] == "no_match" and s["draft"] is None


def test_sourcing_outage_gives_no_match(env):
    env.mock.fail = True
    assert env.signal(AR)["signal"]["status"] == "no_match"


def test_poll_mock_source(env):
    items = env.c.post("/v1/signals/poll", headers=H).json()["items"]
    assert [i["signal"]["status"] for i in items] == ["drafted", "drafted", "ignored"]
    again = env.c.post("/v1/signals/poll", headers=H).json()["items"]
    assert all(i["duplicate"] for i in again)


def test_no_publish_without_approval(env):
    did = env.draft()
    r = env.act(did, "mark-published")
    assert r.status_code == 409
    assert env.c.get(f"/v1/drafts/{did}", headers=H).json()["status"] == "draft"


def test_full_flow_with_audit_and_outcome(env):
    did = env.draft()
    assert env.act(did, "outcome", outcome="replied").status_code == 409
    a = env.act(did, "approve", text="نص معدل من المشرف").json()
    assert (
        a["status"] == "approved"
        and a["approved_by"] == "admin1"
        and a["text"].startswith("نص معدل من المشرف")  # disclosure is re-appended after edits
    )
    p = env.act(did, "mark-published", published_url="https://x.test/c/1").json()
    assert p["status"] == "published"
    o = env.act(did, "outcome", outcome="converted", note="order").json()
    assert o["outcome"] == "converted"
    assert [e["action"] for e in o["audit"]] == [
        "drafted",
        "approved",
        "published",
        "outcome:converted",
    ]
    assert env.act(did, "outcome", outcome="bogus").status_code == 422
    assert env.act(did, "reject").status_code == 409
    assert env.act(did, "approve").status_code == 409


def test_status_machine_reject(env):
    did = env.draft()
    r = env.act(did, "reject", reason="spam").json()
    assert r["status"] == "rejected"
    assert env.act(did, "approve").status_code == 409
    assert env.act(did, "mark-published").status_code == 409
    d2 = env.draft(EN)
    env.act(d2, "approve")
    assert env.act(d2, "reject").json()["status"] == "rejected"


def test_kill_switch_blocks_publish_endpoints(env_off):
    did = env_off.draft()  # drafting itself is allowed
    assert env_off.act(did, "approve").status_code == 403
    assert env_off.act(did, "mark-published").status_code == 403
    assert env_off.c.get(f"/v1/drafts/{did}", headers=H).json()["status"] == "draft"
    assert env_off.c.get("/v1/quota", headers=H).json()["enabled"] is False


def test_daily_cap_enforced_and_resets(env_cap2):
    e = env_cap2
    ids = [e.draft(t) for t in (AR, EN, "need centrifugal pump")]
    assert e.act(ids[0], "approve").status_code == 200
    assert e.act(ids[1], "approve").status_code == 200
    r = e.act(ids[2], "approve")
    assert r.status_code == 429 and r.json()["error"]["code"] == "daily_cap_reached"
    q = e.c.get("/v1/quota", headers=H).json()
    assert q["used_today"] == 2 and q["remaining"] == 0
    # publishing an already approved draft does not consume extra quota
    assert e.act(ids[0], "mark-published").status_code == 200
    assert e.c.get("/v1/drafts/" + ids[2], headers=H).json()["status"] == "draft"
    e.now += timedelta(days=1)
    assert e.act(ids[2], "approve").status_code == 200


def test_cap_zero_blocks_everything():
    app, _ = make(cap=0)
    with TestClient(app) as c:
        e = Env(c, app, None)
        assert e.act(e.draft(), "approve").status_code == 429


def test_list_reads_are_capped(env):
    import asyncio

    from ff_demand import store as store_mod

    for i in range(3):
        env.signal(text=f"{AR} {i}")
    st = env.svc.store
    assert len(asyncio.run(st.list_signals(limit=2))) == 2
    assert len(asyncio.run(st.list_drafts(None, limit=1))) <= 1
    assert store_mod.MAX_LIST == 500
