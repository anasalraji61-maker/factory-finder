"""Moderation: screening, user reports, admin hide/restore, visibility."""

import httpx
import pytest

from ff_sourcing.adapters.mock import MockAdapter
from ff_sourcing.adapters.registry import AdapterRegistry
from ff_sourcing.clients.trust import MockTrustClient, TrustInfo
from ff_sourcing.config import Settings
from ff_sourcing.domain.moderation import banned_categories, contact_kinds, redact
from ff_sourcing.main import create_app

from .test_native import A, B, body, create

GREEN = TrustInfo(supplier_id="x", score=90, band="green")
ADMIN = {"X-Admin-Token": "adm"}
U1, U2, U3, U4 = ({"X-User-Id": f"user_{i}"} for i in range(1, 5))
PREFIX = "/v1/admin/moderation"


def make(**kw):
    kw.setdefault("admin_token", "adm")
    return create_app(
        Settings(database_url="sqlite+aiosqlite:///:memory:", **kw),
        AdapterRegistry([MockAdapter()]),
        MockTrustClient({"sup_native_a": GREEN, "sup_native_b": GREEN}),
    )


@pytest.fixture
async def mc():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=make()), base_url="http://t") as c:
        yield c


async def live(c, **over):
    d = await create(c, **over)
    r = await c.post(f"/v1/my/listings/{d['id']}/publish", headers=A)
    assert r.status_code == 200, r.text
    return d["id"]


async def report(c, lid, who=U1, reason="scam_or_fraud", **extra):
    return await c.post(f"/v1/listings/{lid}/report", json={"reason": reason, **extra}, headers=who)


# ---- screening (pure) --------------------------------------------------------
@pytest.mark.parametrize(
    "text,kind",
    [
        ("see https://shop.example.com/x", "contact_url"),
        ("visit www.mysite.cn", "contact_url"),
        ("order at mysite dot com", "contact_url"),
        ("mail me: sales@factory.cn", "contact_email"),
        ("sales [at] factory.cn", "contact_email"),
        ("call +964 770 123 4567", "contact_phone"),
        ("اتصل على ٠٧٧٠١٢٣٤٥٦٧", "contact_phone"),
        ("whatsapp me", "contact_handle"),
        ("راسلني على واتساب", "contact_handle"),
        ("telegram @best_seller", "contact_handle"),
        ("wa.me/123", "contact_url"),
    ],
)
def test_contact_detected(text, kind):
    assert kind in contact_kinds(text)


@pytest.mark.parametrize(
    "text",
    ["Hand glazed.\nSet of 4.", "Size 120 x 80 x 45 cm, 2.5 kg", "HS 691390 grade A1", "Price 12.50 USD per piece", "طقم ٤ قطع من الخزف"],
)
def test_clean_text_not_flagged(text):
    assert contact_kinds(text) == [] and banned_categories(text) == []


@pytest.mark.parametrize(
    "text,cat",
    [
        ("Selling AK rifles and ammunition", "weapons"),
        ("Rifle", "weapons"),
        ("بيع مسدسات واسلحة", "weapons"),
        ("بيع الحشيش", "drugs"),
        ("cocaine bulk", "drugs"),
        ("Counterfeit watches", "counterfeit"),
        ("جواز مزور", "counterfeit"),
    ],
)
def test_banned_detected(text, cat):
    assert cat in banned_categories(text)


def test_legit_words_not_banned():
    assert banned_categories("Ivory white ceramic, surge suppressor, forged steel bolts, muffler silencer") == []


def test_redact():
    out = redact("mail a@b.com or call 0770 123 4567 or see www.x.com ok")
    assert "a@b.com" not in out and "4567" not in out and "x.com" not in out and out.endswith("ok")


# ---- screening on create/update ---------------------------------------------
async def test_create_flagged_goes_pending_review(mc):
    d = await create(mc, description="Call me on whatsapp +964 770 123 4567")
    assert d["status"] == "pending_review" and d["moderation_source"] == "auto"
    assert "contact" in d["moderation_reason"].lower() and "4567" not in d["moderation_reason"]
    r = await mc.post(f"/v1/my/listings/{d['id']}/publish", headers=A)
    assert r.status_code == 409 and r.json()["error"]["code"] == "under_moderation"
    assert (await mc.get(f"/v1/listings/{d['id']}")).status_code == 404
    assert (await mc.get(f"/v1/my/listings/{d['id']}", headers=A)).json()["status"] == "pending_review"
    assert (await mc.get("/v1/my/listings?status=pending_review", headers=A)).json()["total"] == 1


async def test_banned_goods_in_arabic_title(mc):
    d = await create(mc, title="بيع مسدس حربي", title_ar="مسدس للبيع")
    assert d["status"] == "pending_review" and "weapons" in d["moderation_reason"]


async def test_update_flags_published_and_autolifts(mc):
    lid = await live(mc)
    r = await mc.put(f"/v1/my/listings/{lid}", json=body(title="Great planter www.deal.com"), headers=A)
    assert r.json()["status"] == "pending_review"
    assert (await mc.get(f"/v1/listings/{lid}")).status_code == 404
    found = (await mc.get("/v1/search", params={"q": "planter"})).json()["items"]
    assert all(i["id"] != lid for i in found)
    r = await mc.put(f"/v1/my/listings/{lid}", json=body(), headers=A)  # fixed
    j = r.json()
    assert j["status"] == "published" and "moderation_reason" not in j
    assert (await mc.get(f"/v1/listings/{lid}")).status_code == 200


# ---- reports -----------------------------------------------------------------
async def test_report_requires_user_and_published(mc):
    lid = await live(mc)
    assert (await mc.post(f"/v1/listings/{lid}/report", json={"reason": "other"})).status_code == 401
    assert (await report(mc, lid, reason="bogus")).status_code == 422
    assert (await report(mc, "nat_nope0000")).status_code == 404
    draft = await create(mc)
    assert (await report(mc, draft["id"])).status_code == 404  # drafts are invisible: no existence leak
    assert (await report(mc, "lst_0001")).status_code == 404


async def test_report_dedupe_and_no_leak(mc):
    lid = await live(mc)
    r1 = await report(mc, lid, details="fake, mail me a@b.com or 0770 123 4567")
    r2 = await report(mc, lid)
    assert r1.status_code == r2.status_code == 202 and r1.json() == r2.json() == {"status": "received"}
    items = (await mc.get(f"{PREFIX}/reports", headers=ADMIN)).json()["items"]
    assert len(items) == 1
    it = items[0]
    assert "a@b.com" not in str(it) and "4567" not in str(it) and "user_1" not in str(it)
    assert it["reporter_ref"] and it["listing"]["title"] and it["reason"] == "scam_or_fraud"
    # the owner never sees reports
    assert "report" not in str((await mc.get(f"/v1/my/listings/{lid}", headers=A)).json()).lower()


async def test_report_own_listing_rejected(mc):
    lid = await live(mc)
    r = await mc.post(f"/v1/listings/{lid}/report", json={"reason": "other"}, headers={**U1, **A})
    assert r.status_code == 409
    assert (await mc.get(f"{PREFIX}/reports", headers=ADMIN)).json()["total"] == 0


async def test_report_rate_limited_per_reporter():
    app = make(report_rate_per_hour=2)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        ids = [await live(c, title=f"Planter number {i}") for i in range(3)]
        assert (await report(c, ids[0])).status_code == 202
        assert (await report(c, ids[1])).status_code == 202
        r = await report(c, ids[2])
        assert r.status_code == 429 and "retry-after" in r.headers
        assert (await report(c, ids[2], who=U2)).status_code == 202  # other reporters unaffected


async def test_threshold_moves_to_pending_review(mc):
    lid = await live(mc)
    for who in (U1, U2):
        await report(mc, lid, who)
    assert (await mc.get(f"/v1/listings/{lid}")).status_code == 200
    await report(mc, lid, U3)
    assert (await mc.get(f"/v1/listings/{lid}")).status_code == 404
    d = (await mc.get(f"/v1/my/listings/{lid}", headers=A)).json()
    assert d["status"] == "pending_review" and d["moderation_source"] == "report"
    assert "user" not in d["moderation_reason"].lower().replace("other users", "")
    # owner edits do not lift a report-based review
    assert (await mc.put(f"/v1/my/listings/{lid}", json=body(), headers=A)).json()["status"] == "pending_review"
    # further reports on a hidden listing look like 404
    assert (await report(mc, lid, U4)).status_code == 404
    # admin restore -> published again, open reports dismissed
    r = await mc.post(f"{PREFIX}/listings/{lid}/restore", headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "published"
    assert (await mc.get(f"/v1/listings/{lid}")).status_code == 200
    assert (await mc.get(f"{PREFIX}/reports?status=dismissed", headers=ADMIN)).json()["total"] == 3


# ---- admin ---------------------------------------------------------------------
async def test_admin_auth():
    off = make(admin_token=None)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=off), base_url="http://t") as c:
        assert (await c.get(f"{PREFIX}/reports", headers=ADMIN)).status_code == 404
    on = make()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=on), base_url="http://t") as c:
        for h in ({}, {"X-Admin-Token": "nope"}):
            for m, p in (("GET", "/reports"), ("GET", "/listings"), ("POST", "/listings/nat_x/hide"), ("POST", "/listings/nat_x/restore")):
                r = await c.request(m, PREFIX + p, headers=h, json={"reason": "abc"} if m == "POST" else None)
                assert r.status_code == 401 and r.json()["error"]["code"] == "admin_auth_required"


async def test_internal_token_covers_report_and_admin():
    app = make(internal_token="sek")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get(f"{PREFIX}/reports", headers=ADMIN)).status_code == 401
        assert (await report(c, "nat_x")).status_code == 401
        h = {**ADMIN, "X-Internal-Token": "sek"}
        assert (await c.get(f"{PREFIX}/reports", headers=h)).status_code == 200


async def test_admin_hide_and_restore(mc):
    lid = await live(mc)
    await report(mc, lid)
    assert (await mc.post(f"{PREFIX}/listings/{lid}/hide", json={}, headers=ADMIN)).status_code == 422
    r = await mc.post(f"{PREFIX}/listings/{lid}/hide", json={"reason": "Counterfeit goods"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["status"] == "hidden"
    assert (await mc.get(f"/v1/listings/{lid}")).status_code == 404
    assert all(i["id"] != lid for i in (await mc.get("/v1/search", params={"q": "planter"})).json()["items"])
    d = (await mc.get(f"/v1/my/listings/{lid}", headers=A)).json()
    assert d["status"] == "hidden" and d["moderation_reason"] == "Counterfeit goods" and d["moderation_source"] == "admin"
    assert (await mc.get(f"/v1/my/listings/{lid}", headers=B)).status_code == 404
    # owner cannot publish/unpublish a hidden listing, nor un-hide it via edit
    assert (await mc.post(f"/v1/my/listings/{lid}/publish", headers=A)).status_code == 409
    assert (await mc.post(f"/v1/my/listings/{lid}/unpublish", headers=A)).status_code == 409
    assert (await mc.put(f"/v1/my/listings/{lid}", json=body(), headers=A)).json()["status"] == "hidden"
    listed = (await mc.get(f"{PREFIX}/listings?status=hidden", headers=ADMIN)).json()
    assert listed["total"] == 1 and listed["items"][0]["open_reports"] == 0
    assert (await mc.get(f"{PREFIX}/reports?status=actioned", headers=ADMIN)).json()["total"] == 1
    r = await mc.post(f"{PREFIX}/listings/{lid}/restore", headers=ADMIN)
    assert r.json()["status"] == "published"
    assert (await mc.get(f"/v1/listings/{lid}")).status_code == 200
    assert "moderation_reason" not in (await mc.get(f"/v1/my/listings/{lid}", headers=A)).json()
    assert (await mc.post(f"{PREFIX}/listings/{lid}/restore", headers=ADMIN)).status_code == 409
    assert (await mc.post(f"{PREFIX}/listings/nat_nothere/hide", json={"reason": "abc"}, headers=ADMIN)).status_code == 404


async def test_hide_draft_restores_to_draft(mc):
    d = await create(mc)
    await mc.post(f"{PREFIX}/listings/{d['id']}/hide", json={"reason": "check"}, headers=ADMIN)
    r = await mc.post(f"{PREFIX}/listings/{d['id']}/restore", headers=ADMIN)
    assert r.json()["status"] == "draft"


async def test_delete_removes_reports(mc):
    lid = await live(mc)
    await report(mc, lid)
    assert (await mc.delete(f"/v1/my/listings/{lid}", headers=A)).status_code == 204
    assert (await mc.get(f"{PREFIX}/reports", headers=ADMIN)).json()["total"] == 0
