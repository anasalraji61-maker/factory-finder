"""40 fixture-driven signals: filters, languages, PII scrubbing, disclosure, audit, cooldowns."""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.test_api import Env, H, make

from ff_demand.compliance import scrub_pii
from ff_demand.service import DISCLOSURE

CASES = json.loads((Path(__file__).parent / "fixtures_signals.json").read_text("utf-8"))
PII = re.compile(r"\+?964|770[ -]?123|buyer@example|@buyer_iq|0770")


@pytest.fixture(scope="module")
def results():
    app, _ = make()
    out = []
    with TestClient(app) as c:
        for i, case in enumerate(CASES):
            r = c.post(
                "/v1/signals",
                headers=H,
                json={"text": case["text"], "url": f"https://x.test/p/{i}"},
            )
            assert r.status_code == 201, r.text
            out.append((case, r.json()))
    return out


def test_fixture_count():
    assert len(CASES) == 40


@pytest.mark.parametrize("i", range(40))
def test_status_language_and_pii(results, i):
    case, body = results[i]
    sig, draft = body["signal"], body["draft"]
    assert sig["status"] == case["expect"], case["text"]
    assert not PII.search(sig["text"]), sig["text"]  # contact data never stored
    if case["expect"] == "drafted":
        assert draft["language"] == case["lang"]
        t = draft["text"]
        assert (DISCLOSURE[draft["language"]] in t and "commission" in t.lower()) or draft[
            "language"
        ] == "ar"
        assert not PII.search(t) and not PII.search(json.dumps(sig["intent"], ensure_ascii=False))
        assert not re.search(r"(?i)guarantee|lowest price|ضمان", t)
        assert draft["audit"][0]["action"] == "drafted"
    else:
        assert draft is None


def test_disclosure_mentions_commission():
    assert "commission" in DISCLOSURE["en"] and "عمولة" in DISCLOSURE["ar"]


def test_scrub_pii():
    s = scrub_pii("call +964 770 123 4567 or ٠٧٧٠١٢٣٤٥٦٧ a@b.com @user_1 https://x.test/a")
    assert "[phone]" in s and "[email]" in s and "[handle]" in s and "[link]" in s
    assert not re.search(r"\d{7}", s)
    assert scrub_pii("price 3500-4200 usd") == "price 3500-4200 usd"


def test_duplicate_tracking_params_and_punctuation():
    app, _ = make()
    with TestClient(app) as c:
        a = c.post(
            "/v1/signals",
            headers=H,
            json={"text": "Need pumps", "url": "https://x.test/p/1?utm_source=a&id=3"},
        )
        b = c.post(
            "/v1/signals",
            headers=H,
            json={"text": "other", "url": "https://X.test/p/1?id=3&fbclid=z#frag"},
        )
        assert a.status_code == 201 and b.status_code == 200 and b.json()["duplicate"]
        d1 = c.post("/v1/signals", headers=H, json={"text": "Looking for pumps!!"})
        d2 = c.post("/v1/signals", headers=H, json={"text": "looking   for pumps"})
        assert d1.status_code == 201 and d2.status_code == 200


def test_cooldown_cap_killswitch_and_audit():
    app, _ = make(cap=1)
    with TestClient(app) as c:
        e = Env(c, app, None)
        s1 = c.post(
            "/v1/signals",
            headers=H,
            json={"text": "Need pumps", "url": "https://x.test/a", "author": "Bob"},
        ).json()
        s2 = c.post(
            "/v1/signals",
            headers=H,
            json={"text": "Looking for pump", "url": "https://x.test/b", "author": "@bob"},
        ).json()
        assert e.act(s1["draft"]["id"], "approve").status_code == 200
        r = e.act(s2["draft"]["id"], "approve")  # same author within cooldown (and cap=1)
        assert r.status_code == 429
        acts = [
            a["action"] for a in c.get(f"/v1/drafts/{s1['draft']['id']}", headers=H).json()["audit"]
        ]
        assert acts == ["drafted", "approved"]
    app, _ = make(enabled=False)
    with TestClient(app) as c:
        e = Env(c, app, None)
        d = e.draft("Need pumps")
        assert e.act(d, "approve").status_code == 403
