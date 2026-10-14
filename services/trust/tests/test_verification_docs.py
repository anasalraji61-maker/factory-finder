from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from ff_trust.config import ScoringConfig, Settings
from ff_trust.domain.scoring import assess
from ff_trust.domain.signals import SupplierSignals
from ff_trust.domain.verification import VerificationEvidence, VerifiedDoc
from ff_trust.main import create_app
from ff_trust.verification import VerificationError, VerificationStore, mask_number

CFG = ScoringConfig()
TODAY = date(2026, 10, 15)
TOKEN = "adm-secret"
SUP = {"X-Supplier-Id": "sup_a"}
ADM = {"X-Admin-Token": TOKEN}
NUM = "91310000MA1K3XYZ9876"
F1, F2 = "/v1/media/private/abcdef123456.jpg", "/v1/media/private/fedcba654321.pdf"
BASE = dict(years_in_business=5, verified=True, transactions_count=100, rating_avg=4.0, reviews_count=50)


def doc(**kw):
    d = {"doc_type": "business_license", "issuing_country": "cn", "files": [F1], "number": NUM, "consent": True}
    d.update(kw)
    return d


@pytest.fixture
def client():
    return TestClient(create_app(Settings(admin_token=TOKEN, verification_rate_limit=100)))


def submit(c, sid="sup_a", **kw):
    r = c.post("/v1/trust/verification/documents", json=doc(**kw), headers={"X-Supplier-Id": sid})
    return r


def approve(c, did, **kw):
    return c.post(f"/v1/admin/trust/verification/documents/{did}/decision", json={"decision": "approve", **kw}, headers=ADM)


# ---------------- authorization matrix ----------------
def test_owner_endpoints_need_verified_supplier(client):
    assert client.post("/v1/trust/verification/documents", json=doc()).status_code == 401
    assert client.get("/v1/trust/verification/documents").status_code == 401
    assert client.get("/v1/trust/verification/documents", headers={"X-Supplier-Id": "bad id!"}).status_code == 401
    assert client.get("/v1/trust/verification/documents", headers={"X-User-Id": "u1"}).status_code == 401


def test_admin_404_when_unset_401_when_wrong_and_no_supplier_access():
    off = TestClient(create_app(Settings()))
    for h in ({}, ADM):
        assert off.get("/v1/admin/trust/verification/documents", headers=h).status_code == 404
        assert off.get("/v1/admin/trust/verification/audit", headers=h).status_code == 404
        assert off.post("/v1/admin/trust/verification/documents/x/decision", json={"decision": "approve"}, headers=h).status_code == 404
    c = TestClient(create_app(Settings(admin_token=TOKEN)))
    did = submit(c).json()["id"]
    for path, method, body in (
        ("/documents", "get", None), ("/audit", "get", None),
        (f"/documents/{did}/decision", "post", {"decision": "approve"}), (f"/documents/{did}/expiry", "put", {"expires_on": None}),
    ):  # fmt: skip
        for h in ({}, {"X-Admin-Token": "wrong"}, SUP):
            r = getattr(c, method)("/v1/admin/trust/verification" + path, headers=h, **({"json": body} if body else {}))
            assert r.status_code == 401, (path, h)
    assert c.get("/v1/trust/suppliers/sup_a").status_code == 200
    # a supplier token cannot decide on its own document
    assert c.get("/v1/trust/verification/documents", headers=SUP).json()["items"][0]["status"] == "pending"


def test_owner_isolation(client):
    did = submit(client).json()["id"]
    assert client.get("/v1/trust/verification/documents", headers={"X-Supplier-Id": "sup_b"}).json()["items"] == []
    assert client.delete(f"/v1/trust/verification/documents/{did}", headers={"X-Supplier-Id": "sup_b"}).status_code == 404
    assert client.delete(f"/v1/trust/verification/documents/{did}", headers=SUP).json()["status"] == "withdrawn"


# ---------------- state machine ----------------
def test_state_machine(client):
    d1 = submit(client).json()["id"]
    assert approve(client, d1).json()["status"] == "approved"
    assert approve(client, d1).status_code == 409  # approve twice
    r = client.post(f"/v1/admin/trust/verification/documents/{d1}/decision", json={"decision": "reject"}, headers=ADM)
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    rv = client.post(f"/v1/admin/trust/verification/documents/{d1}/decision", json={"decision": "reject", "reason": "photo mismatch"}, headers=ADM)
    assert rv.json()["status"] == "rejected" and rv.json()["reason"] == "photo mismatch"
    assert approve(client, d1).status_code == 409  # rejected is terminal
    assert client.delete(f"/v1/trust/verification/documents/{d1}", headers=SUP).status_code == 409
    assert client.put(f"/v1/admin/trust/verification/documents/{d1}/expiry", json={"expires_on": "2030-01-01"}, headers=ADM).status_code == 409
    d2 = submit(client, doc_type="bank_reference", number="IBAN-9988776655").json()["id"]
    assert client.delete(f"/v1/trust/verification/documents/{d2}", headers=SUP).json()["status"] == "withdrawn"
    assert approve(client, d2).status_code == 409
    assert approve(client, "nope").status_code == 404
    acts = [e["action"] for e in client.get("/v1/admin/trust/verification/audit?document_id=" + d1, headers=ADM).json()["items"]]
    assert acts == ["revoke", "approve", "submit"]


def test_pending_queue_and_filters(client):
    ids = [submit(client, doc_type="business_license", number=f"LIC-0000{i}XX").json()["id"] for i in range(3)]
    approve(client, ids[0])
    q = client.get("/v1/admin/trust/verification/documents", headers=ADM).json()
    assert q["total"] == 2 and {i["id"] for i in q["items"]} == set(ids[1:])
    assert client.get("/v1/admin/trust/verification/documents?status=all&limit=2", headers=ADM).json()["total"] == 3
    assert client.get("/v1/admin/trust/verification/documents?status=bogus", headers=ADM).status_code == 422


# ---------------- validation ----------------
@pytest.mark.parametrize("bad", [
    {"consent": False}, {"doc_type": "passport"}, {"issuing_country": "CHN"}, {"files": []}, {"files": ["https://evil.example/v1/media/private/abcdef123456.jpg"]},
    {"files": ["/etc/passwd"]}, {"files": ["/v1/media/private/../x.jpg"]}, {"files": ["/v1/media/private/abcdef123456.jpg?x=1"]}, {"files": ["//evil.example/v1/media/private/abcdef123456.jpg"]},
    {"number": None}, {"number": "ab"}, {"expires_on": "2020-01-01"}, {"extra": 1}, {"files": [F1] * 11},
])  # fmt: skip
def test_rejects_bad_input(client, bad):
    body = doc(**bad)
    if bad.get("number", 1) is None:
        body.pop("number")
    r = client.post("/v1/trust/verification/documents", json=body, headers=SUP)
    assert r.status_code == 422, r.text


def test_photos_take_no_number_and_dedupe_files(client):
    assert submit(client, doc_type="factory_photos").status_code == 422
    r = submit(client, doc_type="factory_photos", number=None, files=[F1, F1, F2])
    assert r.status_code == 201 and r.json()["files"] == [F1, F2] and r.json()["number_masked"] is None


def test_absolute_media_url_needs_allowed_host():
    c = TestClient(create_app(Settings(verification_media_hosts=["media.ff.example"])))
    ok = "https://media.ff.example/v1/media/private/abcdef123456.jpg"
    assert submit(c, files=[ok]).status_code == 201
    assert submit(c, files=["http://media.ff.example/v1/media/private/abcdef123456.jpg"], number="OTHER-12345").status_code == 422
    assert submit(c, files=["https://other.example/v1/media/private/abcdef123456.jpg"], number="OTHER-12345").status_code == 422


# ---------------- PII ----------------
def test_no_number_leakage_anywhere(client):
    r = submit(client)
    did = r.json()["id"]
    assert r.json()["number_masked"] == "****9876"
    approve(client, did)
    blobs = [
        r.text,
        client.get("/v1/trust/verification/documents", headers=SUP).text,
        client.get("/v1/admin/trust/verification/documents?status=all", headers=ADM).text,
        client.get("/v1/admin/trust/verification/audit", headers=ADM).text,
        client.get("/v1/trust/suppliers/sup_a").text,
        client.get("/v1/trust/suppliers/sup_a/verification").text,
        client.get("/v1/trust/suppliers/sup_a/history").text,
    ]
    for b in blobs:
        assert NUM not in b and "91310000" not in b and "MA1K3" not in b
    assert "fingerprint" not in "".join(blobs)
    pub = client.get("/v1/trust/suppliers/sup_a/verification").text
    assert F1 not in pub and "9876" not in pub
    dump = "\n".join(_dump_db(client.app))  # nothing in the database contains the raw number
    assert NUM not in dump and "91310000MA1K3" not in dump


def test_mask_short_numbers_fully():
    assert mask_number("ABC1234") == "****" and mask_number("ABCD12345678") == "****5678"


def test_duplicates_and_cross_supplier_flag(client):
    assert submit(client).status_code == 201
    r = submit(client, number=NUM.lower())  # same number, different case
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_document"
    other = submit(client, sid="sup_b").json()
    assert other["status"] == "pending"
    flagged = client.get("/v1/admin/trust/verification/documents", headers=ADM).json()["items"]
    assert all(i["duplicate_elsewhere"] for i in flagged) and len(flagged) == 2
    assert "duplicate_elsewhere" not in client.get("/v1/trust/verification/documents", headers=SUP).json()["items"][0]


# ---------------- caps / rate limits ----------------
def test_rate_limit_and_caps():
    c = TestClient(create_app(Settings(verification_rate_limit=3, verification_max_docs_per_type=10)))
    for i in range(3):
        assert submit(c, number=f"LIC-{i}-ABCDE").status_code == 201
    r = submit(c, number="LIC-9-ABCDE")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert submit(c, sid="sup_other", number="LIC-1-ABCDE").status_code == 201  # per supplier
    c2 = TestClient(create_app(Settings(verification_rate_limit=50, verification_max_docs_per_type=2, verification_max_docs_per_supplier=3)))
    assert [submit(c2, number=f"LIC-{i}-ABCDE").status_code for i in range(3)] == [201, 201, 409]
    assert submit(c2, doc_type="bank_reference", number="ACCT-123456").status_code == 201
    assert submit(c2, doc_type="iso_certificate", number="ISO-123456").status_code == 409  # supplier cap 3


async def test_rate_limit_window_slides():
    now = [datetime(2026, 10, 15, tzinfo=UTC)]
    s = VerificationStore(rate_limit=1, rate_window=60, clock=lambda: now[0])
    await s.submit("s", "business_license", "CN", [F1], "LIC-AAAA-1", None, True)
    with pytest.raises(VerificationError) as ei:
        await s.submit("s", "business_license", "CN", [F1], "LIC-AAAA-2", None, True)
    assert ei.value.status == 429
    now[0] += timedelta(seconds=61)
    await s.submit("s", "business_license", "CN", [F1], "LIC-AAAA-2", None, True)


async def test_total_cap_evicts_only_closed_docs():
    s = VerificationStore(rate_limit=100, max_total=2, max_per_type=10)
    a = await s.submit("s", "business_license", "CN", [F1], "LIC-AAAA-1", None, True)
    await s.submit("s", "business_license", "CN", [F1], "LIC-AAAA-2", None, True)
    with pytest.raises(VerificationError) as ei:
        await s.submit("s", "business_license", "CN", [F1], "LIC-AAAA-3", None, True)
    assert ei.value.status == 503
    await s.withdraw("s", a.id)
    await s.submit("s", "business_license", "CN", [F1], "LIC-AAAA-3", None, True)
    assert len((await s.list_by_status(None, 10, 0))[0]) == 2


# ---------------- expiry ----------------
def test_expiry_set_and_validated(client):
    did = submit(client).json()["id"]
    r = approve(client, did, expires_on="2020-01-01")
    assert r.status_code == 422
    assert approve(client, did, expires_on="2030-05-01").json()["expires_on"] == "2030-05-01"
    e = client.put(f"/v1/admin/trust/verification/documents/{did}/expiry", json={"expires_on": "2031-01-01", "reason": "renewed"}, headers={**ADM, "X-Reviewer": "alice"})
    assert e.json()["expires_on"] == "2031-01-01"
    assert client.put(f"/v1/admin/trust/verification/documents/{did}/expiry", json={"expires_on": "2020-01-01"}, headers=ADM).status_code == 422
    a = client.get("/v1/admin/trust/verification/audit?document_id=" + did, headers=ADM).json()["items"]
    assert a[0]["action"] == "set_expiry" and a[0]["actor"] == "admin:alice" and "2030-05-01 -> 2031-01-01" in a[0]["detail"]


def test_expired_document_stops_counting_and_flags():
    ev = lambda **k: VerificationEvidence(documents=[VerifiedDoc(doc_type="business_license", approved_on=date(2025, 1, 1), **k)])  # noqa: E731
    def run(e, today=TODAY):
        return assess(SupplierSignals(**BASE, verification=e), CFG, today)
    none = assess(SupplierSignals(**BASE), CFG, TODAY)
    fresh = run(ev(expires_on=TODAY + timedelta(days=200)))
    soon = run(ev(expires_on=TODAY + timedelta(days=10)))
    gone = run(ev(expires_on=TODAY - timedelta(days=1)))
    f = lambda a: next((x.impact for x in a.factors if x.key == "document_verification"), 0)  # noqa: E731
    assert f(fresh) == 3 and 0 <= f(soon) <= f(fresh) and f(gone) == 0
    assert gone.score == none.score and gone.verification_level == "none"
    assert "verification_document_expired" in gone.flags and "verification_document_expiring" in soon.flags
    assert soon.verification_level == "basic" and fresh.verification_level == "basic"
    # no expiry: valid for doc_default_validity_days after approval
    assert run(ev(), date(2026, 12, 1)).verification_level == "basic" and run(ev(), date(2027, 2, 1)).verification_level == "none"


def test_decay_is_monotonic():
    pts = []
    for left in (200, 90, 60, 30, 1, 0, -1):
        e = VerificationEvidence(documents=[VerifiedDoc(doc_type="iso_certificate", approved_on=date(2025, 1, 1), expires_on=TODAY + timedelta(days=left))])
        pts.append(next((x.impact for x in assess(SupplierSignals(**BASE, verification=e), CFG, TODAY).factors if x.key == "facility_evidence"), 0))
    assert pts == sorted(pts, reverse=True) and pts[-1] == 0


# ---------------- scoring impact ----------------
def all_docs(**k):
    return VerificationEvidence(documents=[VerifiedDoc(doc_type=t, approved_on=date(2026, 6, 1), **k) for t in (
        "business_license", "company_registry_reference", "bank_reference", "export_license", "factory_photos", "iso_certificate", "other_certificate")])  # fmt: skip


def test_scoring_bounded_bilingual_and_never_negative():
    base = assess(SupplierSignals(**BASE), CFG, TODAY)
    full = assess(SupplierSignals(**BASE, verification=all_docs()), CFG, TODAY)
    fs = {x.key: x for x in full.factors if x.key in ("document_verification", "facility_evidence")}
    assert set(fs) == {"document_verification", "facility_evidence"}
    assert 0 < fs["document_verification"].impact <= CFG.weights["document_verification"]
    assert 0 < fs["facility_evidence"].impact <= CFG.weights["facility_evidence"]
    assert 0 < full.score - base.score <= CFG.weights["document_verification"] + CFG.weights["facility_evidence"]
    for x in fs.values():
        assert x.explanation.endswith("raises the score.") and "يرفع" in x.explanation_ar
    assert "Approved legal / identity documents" in fs["document_verification"].explanation and "مستندات" in fs["document_verification"].explanation_ar
    # duplicates of the same type do not stack
    two = VerificationEvidence(documents=all_docs().documents * 5)
    assert assess(SupplierSignals(**BASE, verification=two), CFG, TODAY).score == full.score


def test_scoring_neutral_when_absent_no_gap_no_confidence_change():
    a, b = assess(SupplierSignals(**BASE), CFG, TODAY), assess(SupplierSignals(**BASE, verification=VerificationEvidence()), CFG, TODAY)
    assert (a.score, a.confidence, a.data_gaps, a.verification_level) == (b.score, b.confidence, b.data_gaps, b.verification_level)
    assert not any(g.key in ("document_verification", "facility_evidence") for g in a.data_gaps)
    full = assess(SupplierSignals(**BASE, verification=all_docs()), CFG, TODAY)
    assert full.confidence == a.confidence


def test_hard_fail_and_caps_still_win():
    s = assess(SupplierSignals(**BASE, sanctions_hit=True, verification=all_docs()), CFG, TODAY)
    assert s.score <= CFG.sanctions_cap and s.band.value == "red" and s.verification_level == "none"
    d = assess(SupplierSignals(**BASE, dispute_rate=0.2, verification=all_docs()), CFG, TODAY)
    assert d.score <= CFG.dispute_severe_cap


def test_badge_levels():
    def lvl(types, audit=None):
        e = VerificationEvidence(documents=[VerifiedDoc(doc_type=t, approved_on=date(2026, 6, 1)) for t in types])
        return assess(SupplierSignals(**BASE, third_party_audit=audit, verification=e), CFG, TODAY).verification_level
    assert lvl([]) == "none"
    assert lvl(["factory_photos", "iso_certificate", "bank_reference"]) == "none"  # no licence/registry
    assert lvl(["business_license"]) == "basic" and lvl(["company_registry_reference", "bank_reference"]) == "basic"
    assert lvl(["business_license", "bank_reference", "factory_photos"]) == "documented"
    assert lvl(["company_registry_reference", "export_license", "iso_certificate"], audit=False) == "documented"
    assert lvl(["business_license", "bank_reference", "factory_photos"], audit=True) == "audited"
    assert lvl(["business_license"], audit=True) == "basic"


# ---------------- end to end ----------------
def test_pending_and_rejected_never_score_approved_does_and_badge_exposed(client):
    c = client
    base = c.get("/v1/trust/suppliers/sup_demo_avg").json()
    assert base["verification_level"] == "none"
    sid = "sup_demo_avg"
    h = {"X-Supplier-Id": sid}
    r1 = c.post("/v1/trust/verification/documents", json=doc(), headers=h).json()
    assert c.get(f"/v1/trust/suppliers/{sid}").json()["score"] == base["score"]  # pending: no effect
    c.post(f"/v1/admin/trust/verification/documents/{r1['id']}/decision", json={"decision": "reject", "reason": "blurry"}, headers=ADM)
    assert c.get(f"/v1/trust/suppliers/{sid}").json()["score"] == base["score"]
    r2 = c.post("/v1/trust/verification/documents", json=doc(number="LIC-REPLACEMENT-1"), headers=h).json()
    approve(c, r2["id"], expires_on="2030-01-01")
    after = c.get(f"/v1/trust/suppliers/{sid}").json()  # cache invalidated by the decision
    assert after["verification_level"] == "basic" and after["score"] > base["score"]
    keys = [f["key"] for f in after["factors"]]
    assert "document_verification" in keys
    pub = c.get(f"/v1/trust/suppliers/{sid}/verification").json()
    assert pub == {"supplier_id": sid, "verification_level": "basic", "label": "Basic verified business", "label_ar": "نشاط تجاري موثق (أساسي)", "valid_types": ["business_license"]}
    mine = c.get("/v1/trust/verification/documents", headers=h).json()
    assert mine["verification_level"] == "basic" and {i["status"] for i in mine["items"]} == {"rejected", "approved"}
    # withdrawing the approved doc drops it again
    c.delete(f"/v1/trust/verification/documents/{r2['id']}", headers=h)
    assert c.get(f"/v1/trust/suppliers/{sid}").json()["score"] == base["score"]


def test_evaluate_accepts_inline_evidence_and_old_payloads_unchanged(client):
    r = client.post("/v1/trust/evaluate", json={**BASE, "verification": {"documents": [{"doc_type": "business_license", "approved_on": "2026-06-01"}]}})
    assert r.status_code == 200 and r.json()["verification_level"] == "basic"
    assert client.post("/v1/trust/evaluate", json=BASE).json()["verification_level"] == "none"
    assert client.post("/v1/trust/evaluate", json={**BASE, "verification": {"documents": [{"doc_type": "x", "approved_on": "2026-06-01"}]}}).status_code == 422


# ---------------- audit log ----------------
async def test_audit_append_only_and_sanitised(client):
    did = submit(client).json()["id"]
    client.post(f"/v1/admin/trust/verification/documents/{did}/decision", json={"decision": "approve", "reason": "ok\n\x00 checked"}, headers={**ADM, "X-Reviewer": "bob<script>"})
    rows = client.get("/v1/admin/trust/verification/audit", headers=ADM).json()["items"]
    assert [r["action"] for r in rows] == ["approve", "submit"] and [r["seq"] for r in rows] == [2, 1]
    assert rows[0]["actor"] == "admin" and rows[0]["reason"] == "ok checked" and rows[1]["actor"] == "supplier:sup_a"
    log = client.app.state.service.verification.audit
    assert not any(hasattr(log, m) for m in ("update", "delete", "remove", "clear", "pop"))
    entry = (await log.list(limit=1))[0]
    with pytest.raises(Exception):
        entry.action = "x"  # frozen entry
    assert client.get("/v1/admin/trust/verification/audit?limit=0", headers=ADM).status_code == 422


async def test_submit_leaves_no_rejected_state_on_failure(client):
    submit(client, consent=False)
    assert client.get("/v1/trust/verification/documents", headers=SUP).json()["items"] == []
    assert await client.app.state.service.verification.audit.count() == 0


def _dump_db(app):
    """Every row of every table as text (runs the async engine on a private loop)."""
    import asyncio

    from sqlalchemy import text

    from ff_trust.db import metadata

    async def go():
        out = []
        async with app.state.db.begin() as conn:
            for name in metadata.tables:
                out += [repr(tuple(r)) for r in (await conn.execute(text(f"select * from {name}"))).all()]
        return out

    return asyncio.run(go())


def test_public_media_refs_rejected_for_verification(client):
    c = client
    for ref in ("/v1/media/files/abcdef123456.jpg", "/v1/media/files/" + "a" * 32 + ".png"):
        r = submit(c, files=[ref])
        assert r.status_code == 422 and r.json()["error"]["code"] == "file_url_not_allowed"
    assert submit(c, files=["/v1/media/private/" + "a" * 32 + ".png"]).status_code in (200, 201)
