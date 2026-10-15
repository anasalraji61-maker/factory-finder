"""Deterministic anti-spam: normalization, near-duplicates, contact obfuscation, velocity, moderation queue."""

import pytest
from conftest import SUP, SUP2, post, sh, uh

from ff_feed import antispam

ADM = {"X-Admin-Token": "adm-secret", "X-User-Id": "admin"}
AS = {"antispam_author_history": 20, "antispam_cross_window_hours": 24}
TEXT = "New CNC machines in stock with fast delivery to Baghdad and Erbil"


def mk(make_client, **kw):
    return make_client(admin_token="adm-secret", rate_posts=0, rate_comments=0, rate_likes=0, rate_reports=0, **{**AS, **kw})


def raw(c, text, supplier=SUP, **extra):
    return c.post("/v1/feed/posts", headers=sh(supplier), json={"body": text, **extra})


# ---------------------------------------------------------------- pure functions
def test_arabic_normalization_folds_variants():
    a = "مكائن الخياطة الجديدة متوفرة في المخزن بسعر ٥٠٠ دولار"
    b = "مَكَائِن الخِيَاطَـة الجديده متوفره في المخزن بسعر 500 دولار"  # tashkeel, tatweel, taa marbuta, digits
    assert antispam.fingerprint(a).digest == antispam.fingerprint(b).digest
    c = "أجهزة إلكترونية آمنة مؤكدة للتصدير والتوريد السريع"
    d = "اجهزه الكترونيه امنه موكده للتصدير والتوريد السريع"  # alef-hamza, taa marbuta
    assert antispam.fingerprint(c).digest == antispam.fingerprint(d).digest
    assert antispam.fingerprint("سيارة هندية جديدة للبيع").digest == antispam.fingerprint("سياره هنديه جديده للبيع").digest
    assert antispam.fingerprint("على الفور مصنع").digest == antispam.fingerprint("علي الفور مصنع").digest  # alef maqsura/ya


def test_similarity_and_min_tokens():
    a, b = antispam.fingerprint(TEXT), antispam.fingerprint(TEXT + " today")
    assert 0.8 < antispam.similarity(a, b) < 1
    assert antispam.similarity(a, antispam.fingerprint("completely different words about steel pipes order")) == 0
    assert not antispam.is_match(antispam.fingerprint("thanks a lot"), antispam.fingerprint("thanks a lot"), 0.9, 4)


@pytest.mark.parametrize(
    "text,kind",
    [
        ("call 0 o 7 o 7 o 1 o 2 o 3 o 4 o 5 o 6", None),  # spaced letters are not glued: no signal
        ("0o7o7o1o2o3o4o5o6", "obfuscated_phone"),
        ("zero seven seven zero one two three four five", "obfuscated_phone"),
        ("صفر سبعة سبعة صفر واحد اثنين ثلاثة اربعة", "obfuscated_phone"),
        ("٠_٧_٧_١_٢_٣_٤_٥_٦", "obfuscated_phone"),
        ("great prices, dm me for details", "solicitation"),
        ("راسلني على الخاص للتفاصيل", "solicitation"),
        ("buy buy buy buy buy buy buy buy buy now", "flooding"),
        ("size 12.5x3.4x5.6 weight 7.8 kg", None),
    ],
)
def test_suspicious_signals(text, kind):
    got = antispam.suspicious_signals(text)
    assert (kind in got) if kind else not got


# ---------------------------------------------------------------- same author -> 409
def test_same_author_exact_and_normalized_duplicate_rejected(make_client):
    c = mk(make_client)
    assert raw(c, "مكائن الخياطة الجديدة متوفرة الآن بسعر ٥٠٠ دولار").status_code == 201
    r = raw(c, "مَكائِنُ الخياطه الجديده متوفره الان بسعر 500 دولار")
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_content"
    assert "مكائن" not in r.text


def test_same_author_near_duplicate_rejected_but_distinct_ok(make_client):
    c = mk(make_client)
    assert raw(c, TEXT).status_code == 201
    assert raw(c, TEXT + " today").status_code == 409
    assert raw(c, "Fresh olive oil from Basra farms, 20 tonnes ready for export now").status_code == 201


def test_same_author_check_off_and_exact_only(make_client):
    c = mk(make_client, antispam_author_history=0)
    assert raw(c, TEXT).status_code == 201 and raw(c, TEXT).status_code == 201
    c2 = mk(make_client, antispam_author_similarity=0)
    assert raw(c2, TEXT, SUP2).status_code == 201
    assert raw(c2, TEXT + " today", SUP2).status_code == 201  # near match ignored
    assert raw(c2, TEXT, SUP2).status_code == 409  # exact still blocked


def test_history_window_is_last_n_posts(make_client):
    c = mk(make_client, antispam_author_history=2)
    assert raw(c, TEXT).status_code == 201
    raw(c, "Second unrelated announcement about plastic granules and resin")
    raw(c, "Third unrelated announcement about copper wire spools stock")
    assert raw(c, TEXT).status_code == 201  # the original fell out of the last-2 window


def test_duplicate_comment_by_same_user_rejected(make_client):
    c = mk(make_client)
    p = post(c)
    u = uh("buyer1")
    body = {"body": "هل السعر نهائي للكمية الكبيرة؟ نحتاج عرض"}
    assert c.post(f"/v1/feed/posts/{p['id']}/comments", headers=u, json=body).status_code == 201
    r = c.post(f"/v1/feed/posts/{p['id']}/comments", headers=u, json={"body": "هَل السِّعر نهائي للكميه الكبيره نحتاج عرض"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_content"


# ---------------------------------------------------------------- cross author -> needs_review
def test_cross_author_near_duplicate_goes_to_review(make_client):
    c = mk(make_client)
    a = raw(c, TEXT, SUP)
    assert a.status_code == 201 and "status" not in a.json()
    b = raw(c, TEXT + " now", SUP2)  # different author, near duplicate
    assert b.status_code == 201 and b.json()["status"] == "needs_review"
    pid = b.json()["id"]
    # hidden from every public surface, visible to its author
    assert c.get(f"/v1/feed/posts/{pid}", headers=uh("buyer9")).status_code == 404
    assert c.get(f"/v1/feed/posts/{pid}").status_code == 404
    own = c.get(f"/v1/feed/posts/{pid}", headers=sh(SUP2))
    assert own.status_code == 200 and own.json()["status"] == "needs_review"
    ids = lambda r: [i["id"] for i in r.json()["items"]]  # noqa: E731
    assert pid not in ids(c.get("/v1/feed/trending")) and pid not in ids(c.get("/v1/feed/home", headers=uh("buyer9")))
    assert pid not in ids(c.get(f"/v1/feed/suppliers/{SUP2}/posts", headers=uh("buyer9")))
    assert pid in ids(c.get(f"/v1/feed/suppliers/{SUP2}/posts", headers=sh(SUP2)))
    assert c.put(f"/v1/feed/posts/{pid}/like", headers=uh("buyer9")).status_code == 404
    # admin queue (default = hidden + needs_review), then restore publishes it
    q = c.get("/v1/admin/feed/posts", headers=ADM).json()["items"]
    assert [i["id"] for i in q] == [pid] and q[0]["status"] == "needs_review"
    assert q[0]["hidden_reason"].startswith("antispam: cross_author_duplicate")
    assert [i["id"] for i in c.get("/v1/admin/feed/posts?status=needs_review", headers=ADM).json()["items"]] == [pid]
    assert c.post(f"/v1/admin/feed/posts/{pid}/restore", headers=ADM).json()["status"] == "published"
    assert c.get(f"/v1/feed/posts/{pid}", headers=uh("buyer9")).status_code == 200


def test_cross_author_outside_window_is_fine(make_client, clock):
    c = mk(make_client)
    assert raw(c, TEXT, SUP).status_code == 201
    clock.advance(hours=25)
    r = raw(c, TEXT, SUP2)
    assert r.status_code == 201 and "status" not in r.json()


def test_cross_author_arabic_variants_and_disable(make_client):
    c = mk(make_client)
    raw(c, "مصنع بلاستيك يعرض خطوط إنتاج مستعملة بحالة ممتازة للبيع الآن", SUP)
    r = raw(c, "مصنع بلاستيك يعرض خطوط انتاج مستعمله بحاله ممتازه للبيع الان", SUP2)
    assert r.json()["status"] == "needs_review"
    c2 = mk(make_client, antispam_cross_window_hours=0)
    raw(c2, TEXT, SUP)
    assert "status" not in raw(c2, TEXT, SUP2).json()


def test_cross_author_comment_held_not_counted(make_client):
    c = mk(make_client)
    p = post(c)
    text = "Please send the full price list and minimum order quantity today"
    assert c.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh("u1"), json={"body": text}).status_code == 201
    r = c.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh("u2"), json={"body": text})
    assert r.status_code == 201 and r.json()["status"] == "needs_review"
    pub = c.get(f"/v1/feed/posts/{p['id']}/comments", headers=uh("u3")).json()["items"]
    mine = c.get(f"/v1/feed/posts/{p['id']}/comments", headers=uh("u2")).json()["items"]
    assert len(pub) == 1 and len(mine) == 2
    assert c.get(f"/v1/feed/posts/{p['id']}", headers=uh("u3")).json()["comment_count"] == 1
    held = c.get("/v1/admin/feed/comments", headers=ADM).json()["items"]
    assert [i["id"] for i in held] == [r.json()["id"]]
    c.post(f"/v1/admin/feed/comments/{held[0]['id']}/restore", headers=ADM)
    assert c.get(f"/v1/feed/posts/{p['id']}", headers=uh("u3")).json()["comment_count"] == 2


# ---------------------------------------------------------------- contact / suspicious
def test_plain_contact_info_still_rejected_and_obfuscated_is_reviewed(make_client):
    c = mk(make_client)
    assert raw(c, "Call me on +964 770 123 4567 for the best prices").status_code == 422  # existing behaviour
    assert raw(c, "Join t.me/mychannel for the best prices please").status_code == 422
    r = raw(c, "Best prices call zero seven seven zero one two three four five six")
    assert r.status_code == 201 and r.json()["status"] == "needs_review"
    held = c.get("/v1/admin/feed/posts", headers=ADM).json()["items"][0]
    assert "obfuscated_phone" in held["hidden_reason"]
    c2 = mk(make_client, antispam_suspicious=0)
    assert "status" not in raw(c2, "Best prices call zero seven seven zero one two three four five six").json()


# ---------------------------------------------------------------- velocity
def test_velocity_holds_burst_posts(make_client, clock):
    c = mk(make_client, antispam_velocity_posts=3, antispam_velocity_window_seconds=60)
    topics = ["steel pipes", "olive oil", "cotton yarn", "copper wire", "plastic resin"]
    out = [raw(c, f"Fresh stock announcement number {i} about {t} for export").json() for i, t in enumerate(topics)]
    assert [o.get("status") for o in out] == [None, None, None, "needs_review", "needs_review"]
    clock.advance(seconds=120)
    assert "status" not in raw(c, "A calm later announcement about ceramic tiles shipment ready").json()


def test_velocity_disabled_by_zero(make_client):
    c = mk(make_client, antispam_velocity_posts=0)
    for i in range(6):
        assert "status" not in raw(c, f"Distinct announcement {i} regarding product line {chr(97 + i) * 5} ready").json()


def test_velocity_comments(make_client):
    c = mk(make_client, antispam_velocity_comments=2)
    p = post(c)
    st = [
        c.post(f"/v1/feed/posts/{p['id']}/comments", headers=uh("u1"), json={"body": t}).json().get("status")
        for t in ("what is the lead time please", "can you ship to Basra port", "is a sample available for testing")
    ]
    assert st == [None, None, "needs_review"]
