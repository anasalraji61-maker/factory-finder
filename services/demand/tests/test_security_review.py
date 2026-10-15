import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from ff_demand.config import Settings
from ff_demand.main import create_app
from ff_demand.service import DISCLOSURE
from ff_demand.signals import MockSignalSource
from ff_demand.sourcing import MockSourcingClient

H = {"X-User-Id": "admin1"}
AR = "أحتاج مكائن تعبئة من الصين"


class Env:
    def __init__(self, client, app):
        self.c, self.svc = client, app.state.service
        self.svc.clock = lambda: datetime(2026, 10, 14, 10, 0, tzinfo=UTC)

    def draft(self):
        d = self.c.post("/v1/signals", headers=H, json={"text": AR}).json()["draft"]
        assert d
        return d["id"]

    def act(self, did, action, **body):
        return self.c.post(f"/v1/drafts/{did}/{action}", headers=H, json=body)


def make():
    app = create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:", enabled=True, daily_cap=20),
        sourcing=MockSourcingClient(),
        source=MockSignalSource(),
    )
    return app, None


@pytest.fixture
def env():
    app, _ = make()
    with TestClient(app) as c:
        yield Env(c, app)


def test_edited_text_cannot_strip_the_disclosure(env):
    did = env.draft()
    r = env.act(did, "approve", text="هلا بيك، عندنا خيارات مناسبة لطلبك على المنصة")
    assert r.status_code == 200
    assert DISCLOSURE["ar"] in r.json()["text"]


def test_published_url_must_be_http_or_https(env):
    did = env.draft()
    env.act(did, "approve")
    assert env.act(did, "mark-published", published_url="javascript:alert(1)").status_code == 422
    assert (
        env.act(did, "mark-published", published_url="https://example.test/p/1").status_code == 200
    )


def test_signal_url_must_be_http_or_https(env):
    r = env.c.post("/v1/signals", headers=H, json={"text": AR, "url": "file:///etc/passwd"})
    assert r.status_code == 422


def test_concurrent_approvals_never_exceed_cap(tmp_path):
    cap = 2
    app = create_app(
        Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/d.db", enabled=True, daily_cap=cap),
        sourcing=MockSourcingClient(),
        source=MockSignalSource(),
    )
    with TestClient(app):
        svc = app.state.service

        async def run():
            ids = []
            for i in range(6):
                r = await svc.import_signal(
                    __import__("ff_demand.signals", fromlist=["RawSignal"]).RawSignal(
                        AR + f" {i}", None, "manual"
                    )
                )
                ids.append(r["draft"]["id"])
            res = await asyncio.gather(
                *(svc.approve(d, "a", None) for d in ids), return_exceptions=True
            )
            return res, await svc.quota()

        res, q = asyncio.run(run())
        assert sum(1 for r in res if isinstance(r, dict)) == cap
        assert q["used_today"] == cap


def test_listing_text_cannot_inject_links_or_newlines():
    from decimal import Decimal

    from ff_demand.service import build_reply
    from ff_demand.sourcing import Candidate

    c = Candidate(
        id="l1",
        title="Pump\nVisit http://evil.test/x now",
        title_ar=None,
        supplier_name="S\r\nBcc: x",
        price_min=Decimal("1"),
        price_max=Decimal("2"),
        currency="USD",
    )
    text = build_reply("en", [c])
    assert "evil.test" not in text and "\r" not in text
    assert sum(1 for ln in text.split("\n") if ln.startswith("- ")) == 1


def test_audit_trail_is_capped():
    from ff_demand.service import MAX_AUDIT, _audit

    d = {"audit": [{"action": "drafted"}]}
    for i in range(MAX_AUDIT * 3):
        _audit(d, {"action": f"outcome:{i}"})
    assert len(d["audit"]) == MAX_AUDIT
    assert d["audit"][0]["action"] == "drafted"
    assert d["audit"][-1]["action"] == f"outcome:{MAX_AUDIT * 3 - 1}"


def test_retention_purges_only_inert_signals_and_rejected_drafts(env):
    from datetime import timedelta

    c, s = env.c, env.svc
    new = s.clock()
    s.clock = lambda: new - timedelta(days=200)
    ignored = c.post("/v1/signals", headers=H, json={"text": "nice weather today"}).json()["signal"]
    rejected = env.draft()
    env.act(rejected, "reject")
    sig = {"text": "I need packaging machines from China"}
    approved = c.post("/v1/signals", headers=H, json=sig).json()["draft"]["id"]
    assert env.act(approved, "approve").status_code == 200
    sig = {"text": "I need bottle filling machines from China"}
    pending = c.post("/v1/signals", headers=H, json=sig).json()["draft"]["id"]
    s.clock = lambda: new
    assert c.post("/v1/signals/poll", headers=H).status_code == 200  # poll runs the retention pass
    assert c.get(f"/v1/drafts/{approved}", headers=H).status_code == 200  # audit record kept
    assert c.get(f"/v1/drafts/{pending}", headers=H).status_code == 200
    assert c.get(f"/v1/drafts/{rejected}", headers=H).status_code == 404
    assert c.get(f"/v1/signals/{ignored['id']}", headers=H).status_code == 404
