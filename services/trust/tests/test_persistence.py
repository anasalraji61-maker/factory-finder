"""Persistence: restart survival, atomic transitions, append-only audit, keyed fingerprints, retention, caps."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from ff_trust.config import Settings
from ff_trust.db import Database, score_snapshots
from ff_trust.main import create_app
from ff_trust.store import CapacityReached, ReportStore, Snapshot, SnapshotStore
from ff_trust.verification import MediaRules, VerificationError, VerificationStore

TOKEN = "adm-secret"
KEY = "k" * 32
SUP = {"X-Supplier-Id": "sup_a"}
ADM = {"X-Admin-Token": TOKEN}
USER = {"X-User-Id": "u1"}
F1 = "/v1/media/files/abcdef123456.jpg"
DOC = {"doc_type": "business_license", "issuing_country": "cn", "files": [F1], "number": "91310000MA1K3XYZ9876", "consent": True}


def url(tmp_path):
    return f"sqlite+aiosqlite:///{tmp_path}/trust.db"


def make(tmp_path, **kw):
    kw.setdefault("admin_token", TOKEN)
    kw.setdefault("verification_hash_key", KEY)
    kw.setdefault("verification_rate_limit", 100)
    return TestClient(create_app(Settings(database_url=url(tmp_path), **kw)))


# ---------------- restart survival ----------------
def test_everything_survives_a_restart(tmp_path):
    with make(tmp_path) as c1:
        did = c1.post("/v1/trust/verification/documents", json=DOC, headers=SUP).json()["id"]
        assert c1.post(f"/v1/admin/trust/verification/documents/{did}/decision", json={"decision": "approve"}, headers=ADM).status_code == 200
        base = c1.get("/v1/trust/suppliers/sup_demo_avg").json()["score"]
        rid = c1.post("/v1/trust/suppliers/sup_demo_avg/report", json={"type": "fraud", "text": "x"}, headers=USER).json()["id"]
        asyncio.run(c1.app.state.service.review_report(rid, "accepted"))
        scored = c1.get("/v1/trust/suppliers/sup_a")
        hist1 = c1.get("/v1/trust/suppliers/sup_demo_avg/history").json()["points"]
        audit1 = c1.get("/v1/admin/trust/verification/audit", headers=ADM).json()["items"]
    assert scored.status_code == 200
    with make(tmp_path) as c2:  # brand-new app instance, same sqlite file
        docs = c2.get("/v1/trust/verification/documents", headers=SUP).json()
        assert [d["status"] for d in docs["items"]] == ["approved"] and docs["verification_level"] == "basic"
        assert c2.get("/v1/admin/trust/verification/audit", headers=ADM).json()["items"] == audit1
        assert c2.get("/v1/trust/suppliers/sup_demo_avg").json()["score"] < base  # accepted report still counts
        assert [p for p in c2.get("/v1/trust/suppliers/sup_demo_avg/history").json()["points"] if p["source"] == "snapshot"]
        assert len(hist1) <= len(c2.get("/v1/trust/suppliers/sup_demo_avg/history").json()["points"])
        dup = c2.post("/v1/trust/verification/documents", json={**DOC, "number": DOC["number"].lower()}, headers=SUP)
        assert dup.status_code == 409 and dup.json()["error"]["code"] == "duplicate_document"  # keyed hash is stable
        assert c2.post("/v1/trust/verification/documents", json=DOC, headers={"X-Supplier-Id": "sup_b"}).status_code == 201


def test_report_rate_limit_survives_restart(tmp_path):
    post = lambda c: c.post("/v1/trust/suppliers/s/report", json={"type": "other", "text": "x"}, headers=USER)  # noqa: E731
    with make(tmp_path, report_rate_limit=1) as c1:
        assert post(c1).status_code == 201
    with make(tmp_path, report_rate_limit=1) as c2:
        assert post(c2).status_code == 429


def test_dev_key_is_persisted_so_duplicates_survive_restart_without_env_key(tmp_path):
    with make(tmp_path, verification_hash_key=None) as c1:
        assert c1.post("/v1/trust/verification/documents", json=DOC, headers=SUP).status_code == 201
    with make(tmp_path, verification_hash_key=None) as c2:
        r = c2.post("/v1/trust/verification/documents", json=DOC, headers=SUP)
        assert r.status_code == 409


def test_production_requires_hash_key(monkeypatch, tmp_path):
    monkeypatch.setenv("FF_ENV", "production")
    with pytest.raises(RuntimeError, match="FF_TRUST_VERIFICATION_HASH_KEY"):
        create_app(Settings(database_url=url(tmp_path)))
    app = create_app(Settings(database_url=url(tmp_path), verification_hash_key=KEY))
    with TestClient(app) as c:
        assert c.get("/ready").status_code == 200
    with pytest.raises(RuntimeError, match="differs"):  # a changed key would silently disable duplicate detection
        with TestClient(create_app(Settings(database_url=url(tmp_path), verification_hash_key="z" * 32))):
            pass


def test_default_settings_and_url_handling(monkeypatch):
    monkeypatch.delenv("FF_TRUST_DATABASE_URL")
    s = Settings()
    assert s.database_url.startswith("sqlite+aiosqlite:///") and s.auto_create_tables is True
    assert Settings(database_url="postgresql://u:p@h/db").auto_create_tables is False
    assert Settings(database_url="postgresql://u:p@h/db", db_auto_create=True).auto_create_tables is True
    monkeypatch.setenv("FF_TRUST_DATABASE_URL", "")  # compose passes empty strings: falls back to the default
    assert Settings().database_url == s.database_url
    from ff_trust.dburl import normalize_database_url

    assert normalize_database_url("postgres://u:p@h/db") == "postgresql+asyncpg://u:p@h/db"


def test_ready_checks_database(tmp_path):
    with make(tmp_path) as c:
        assert c.get("/ready").json()["checks"] == {"database": True}


def test_default_file_database_is_created_in_data_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FF_TRUST_DATABASE_URL")
    with TestClient(create_app(Settings())) as c:
        assert c.get("/v1/trust/suppliers/sup_demo_avg").status_code == 200
    assert (tmp_path / "data" / "trust.db").exists()


# ---------------- atomic transitions ----------------
def two_stores(tmp_path, **kw):
    mk = lambda: VerificationStore(MediaRules(), db=Database(url(tmp_path), True), hash_key=KEY, rate_limit=100, **kw)  # noqa: E731
    return mk(), mk()  # two engines on one file = two "processes"


async def test_concurrent_approvals_only_one_wins(tmp_path):
    a, b = two_stores(tmp_path)
    d = await a.submit("s", "business_license", "CN", [F1], "LIC-AAAA-1", None, True)
    res = await asyncio.gather(a.decide(d.id, "approve", None, "admin:a"), b.decide(d.id, "approve", None, "admin:b"), return_exceptions=True)
    ok = [r for r in res if not isinstance(r, Exception)]
    bad = [r for r in res if isinstance(r, VerificationError)]
    assert len(ok) == 1 and len(bad) == 1 and bad[0].code == "invalid_transition" and bad[0].status == 409
    actions = [e.action for e in await a.audit.list(d.id)]
    assert sorted(actions) == ["approve", "submit"]  # exactly one approve audit row


async def test_concurrent_approve_vs_withdraw_never_both(tmp_path):
    a, b = two_stores(tmp_path)
    d = await a.submit("s", "business_license", "CN", [F1], "LIC-AAAA-1", None, True)
    await asyncio.gather(a.decide(d.id, "approve", None, "admin"), b.withdraw("s", d.id), return_exceptions=True)
    final = (await a.get(d.id)).status
    rows = [(e.action, e.from_status, e.to_status) for e in reversed(await a.audit.list(d.id))]
    assert final in ("approved", "withdrawn")
    # the audit chain is a valid walk through the state machine ending in the stored status
    assert rows[0] == ("submit", None, "pending") and rows[1][1] == "pending" and rows[-1][2] == final
    for prev, nxt in zip(rows, rows[1:], strict=False):
        assert prev[2] == nxt[1]


async def test_concurrent_identical_submissions_one_row(tmp_path):
    a, b = two_stores(tmp_path)
    res = await asyncio.gather(*(s.submit("s", "business_license", "CN", [F1], "LIC-AAAA-1", None, True) for s in (a, b)), return_exceptions=True)
    assert sum(isinstance(r, VerificationError) and r.code == "duplicate_document" for r in res) == 1
    assert len(await a.list_for_supplier("s")) == 1


async def test_reject_after_approve_is_revoke_and_terminal(tmp_path):
    a, _ = two_stores(tmp_path)
    d = await a.submit("s", "business_license", "CN", [F1], "LIC-AAAA-1", None, True)
    await a.decide(d.id, "approve", None, "admin")
    r = await a.decide(d.id, "reject", "fake", "admin")
    assert r.status == "rejected"
    with pytest.raises(VerificationError) as ei:
        await a.decide(d.id, "approve", None, "admin")
    assert ei.value.code == "invalid_transition"
    assert [e.action for e in await a.audit.list(d.id)] == ["revoke", "approve", "submit"]


async def test_concurrent_report_reviews_are_consistent(tmp_path):
    db1, db2 = Database(url(tmp_path), True), Database(url(tmp_path), True)
    r1, r2 = ReportStore(db=db1), ReportStore(db=db2)
    rep = await r1.add("s", "u", "fraud", "x")
    await asyncio.gather(r1.review(rep.id, "accepted"), r2.review(rep.id, "rejected"))
    final = (await r1.get(rep.id)).status
    assert final in ("accepted", "rejected") and await r1.accepted_count("s") == (final == "accepted")


# ---------------- append-only audit (database level) ----------------
async def test_audit_rejects_update_and_delete_at_database_level(tmp_path):
    a, _ = two_stores(tmp_path)
    d = await a.submit("s", "business_license", "CN", [F1], "LIC-AAAA-1", None, True)
    async with a.db.engine.connect() as conn:
        for stmt in ("UPDATE verification_audit SET actor='x'", "DELETE FROM verification_audit"):
            with pytest.raises(sa.exc.DBAPIError, match="append-only"):
                await conn.execute(sa.text(stmt))
            await conn.rollback()
    assert [e.actor for e in await a.audit.list(d.id)] == ["supplier:s"]
    assert not any(hasattr(a.audit, m) for m in ("update", "delete", "remove", "clear", "pop", "purge"))
    paths = create_app(Settings()).openapi()["paths"]
    audit_paths = [p for p in paths if "audit" in p]
    assert audit_paths and all(set(paths[p]) == {"get"} for p in audit_paths)  # no write verbs on the audit log


# ---------------- caps and retention ----------------
async def test_report_retention_keeps_accepted_and_caps_total(tmp_path):
    t = [datetime(2026, 1, 1, tzinfo=UTC)]
    s = ReportStore(limit=100, window_seconds=60, clock=lambda: t[0], max_reports=3, retention_days=30, db=Database(url(tmp_path), True))
    keep = await s.add("s", "u1", "fraud", "a")
    await s.review(keep.id, "accepted")
    gone = await s.add("s", "u2", "fraud", "b")
    await s.review(gone.id, "rejected")
    await s.add("s", "u3", "fraud", "c")
    await s.add("s", "u4", "fraud", "d")  # full: evicts the rejected one first
    assert await s.get(gone.id) is None and await s.get(keep.id) is not None
    t[0] += timedelta(days=31)
    assert await s.purge() == 2  # both pending ones
    assert await s.get(keep.id) is not None and await s.accepted_count("s") == 1
    for i in range(2):  # fill with accepted reports only -> refuse instead of evicting evidence
        x = await s.add("s", f"v{i}", "fraud", "e")
        await s.review(x.id, "accepted")
    with pytest.raises(CapacityReached):
        await s.add("s", "late", "fraud", "f")


async def test_snapshot_dedup_cap_and_retention(tmp_path):
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    now = [t0 + timedelta(days=400)]
    s = SnapshotStore(Database(url(tmp_path), True), max_per_supplier=3, max_total=4, retention_days=365, clock=lambda: now[0])
    snap = lambda i, score: Snapshot(t0 + timedelta(days=i), score, "yellow", 50)  # noqa: E731
    await s.add("a", snap(0, 60))
    await s.add("a", snap(1, 60))  # unchanged -> skipped
    for i, sc in enumerate((61, 62, 63, 64), start=2):
        await s.add("a", snap(i, sc))
    assert [x.score for x in await s.list("a")] == [62, 63, 64]  # per-supplier cap keeps the newest
    for i in range(3):
        await s.add("b", Snapshot(now[0] - timedelta(days=i), 50 + i, "yellow", 40))
    await s.purge()
    async with s.db.begin() as conn:
        assert (await conn.execute(sa.select(sa.func.count()).select_from(score_snapshots))).scalar_one() <= 4
    now[0] += timedelta(days=400)
    assert await s.purge() >= 1 and await s.list("a") == []
