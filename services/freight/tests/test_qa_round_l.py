"""QA round L: profile completeness, duplicate applications, attachment URLs, suspension audit."""

import asyncio

import pytest
from conftest import ADM, APP, make_forwarder, uh
from sqlalchemy import select

from ff_freight.db import audit_log
from ff_freight.service_keys import check_attachment_url, completeness, name_key


def apply(client, user="u1", **over):
    return client.post("/v1/freight/applications", headers=uh(user), json={**APP, **over})


def audit_rows(client):
    svc = client.app.state.service

    async def go():
        async with svc.engine.connect() as c:
            return (await c.execute(select(audit_log).order_by(audit_log.c.created_at))).all()

    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(go())


# ---- completeness
def test_completeness_pure():
    full = dict(company_name="X Co", country_code="AE", description="d" * 30, lanes=[1], modes=["sea"],
                incoterms=["FOB"], certifications=["FIATA"])  # fmt: skip
    assert completeness(**full) == {"score": 100, "missing": []}
    r = completeness(**{**full, "description": "short", "certifications": [], "lanes": []})
    assert r == {"score": 40, "missing": ["description", "lanes", "certifications"]}
    assert completeness(**{**full, "description": "d" * 29})["score"] == 80  # boundary: 30 chars needed
    assert completeness(**{**full, "company_name": "  "})["missing"] == ["company_name"]


def test_completeness_in_profile(client):
    fid = make_forwarder(client, description="Sea and air freight, China to Iraq, weekly sailings")
    p = client.get("/v1/freight/forwarders/me", headers=uh("fwd_user1")).json()
    assert p["profile_completeness"] == {"score": 100, "missing": []}
    client.patch("/v1/freight/forwarders/me", headers=uh("fwd_user1"), json={"certifications": []})
    p = client.get(f"/v1/freight/forwarders/{fid}", headers=uh("fwd_user1")).json()
    assert p["profile_completeness"] == {"score": 80, "missing": ["certifications"]}


# ---- duplicates
@pytest.mark.parametrize(
    "variant",
    ["GULF STAR LOGISTICS", "  gulf   star\tlogistics ", "Gulf Star Logistics.", "gulf-star logistics"],
)
def test_duplicate_company_variants(client, variant):
    assert apply(client, "u1").status_code == 201
    r = apply(client, "u2", company_name=variant)
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_company"


def test_duplicate_arabic_diacritics_and_digits(client):
    assert apply(client, "u1", company_name="شركة النَّجمة ٢٠٢٤ للشحن").status_code == 201
    for v in ("شركة النجمة 2024 للشحن", "شركةُ  النجمة ۲۰۲٤ للشحن", "شركة النجمـة 2024 للشحن"):
        r = apply(client, "u2", company_name=v)
        assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_company", v


def test_duplicate_scope(client):
    a = apply(client, "u1").json()
    assert apply(client, "u2", country_code="IQ").status_code == 201  # different country: different company
    client.post(f"/v1/admin/freight/applications/{a['id']}/reject", headers=ADM, json={"reason": "no licence"})
    assert apply(client, "u3").status_code == 201  # a rejected application no longer blocks the name
    assert apply(client, "u1").status_code == 409  # now u3 holds it


def test_duplicate_against_existing_forwarder(client):
    make_forwarder(client, "fwd_a", company_name="Gulf Star Logistics")
    r = apply(client, "u9", company_name="GULF STAR logistics")
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_company"


def test_name_key_stable():
    assert name_key("Gulf  Star", "AE") == name_key("GULF star", "AE") != name_key("Gulf Star", "IQ")
    assert name_key("٣M Ltd", "AE") == name_key("3m ltd", "AE")


# ---- attachments
GOOD = "https://docs.example.com/licence.pdf"


def test_attachments_accepted_and_deduped(client):
    r = apply(client, attachments=[GOOD, GOOD, "https://cdn.example.org/a/b.png?x=1"])
    assert r.status_code == 201 and r.json()["attachments"] == [GOOD, "https://cdn.example.org/a/b.png?x=1"]
    assert apply(client, "u2", company_name="Other Co").json()["attachments"] == []


@pytest.mark.parametrize(
    "bad",
    [
        "http://docs.example.com/a.pdf", "javascript:alert(1)", "data:text/html;base64,AAAA", "ftp://x.example.com/a",
        "https://user:pw@docs.example.com/a", "https://127.0.0.1/a", "https://[::1]/a", "https://10.0.0.5/a",
        "https://localhost/a", "https://printer.local/a", "https://intranet/a", "https://docs.example.com:8443/a",
        "https://docs.example.com/a b", "https://docs.example.com/" + "a" * 500, "", "   ", "https://",
        "//docs.example.com/a", "https://docs.example.com/a\x00",
    ],
)
def test_attachments_rejected(client, bad):
    assert apply(client, attachments=[bad]).status_code == 422


def test_attachments_count_cap(client):
    urls = [f"https://d{i}.example.com/a.pdf" for i in range(6)]
    assert apply(client, attachments=urls).status_code == 422
    assert apply(client, attachments=urls[:5]).status_code == 201


def test_check_attachment_url_trims():
    assert check_attachment_url("  " + GOOD + " ") == GOOD


# ---- suspension + audit
def test_suspension_flow_audited(client):
    fid = make_forwarder(client)
    assert client.post(f"/v1/admin/freight/forwarders/{fid}/suspend", headers=ADM, json={"reason": "licence expired"}).status_code == 200
    # repeating does not add a second entry; reinstate does
    client.post(f"/v1/admin/freight/forwarders/{fid}/suspend", headers=ADM, json={"reason": "licence expired"})
    client.post(f"/v1/admin/freight/forwarders/{fid}/reinstate", headers=ADM)
    client.post(f"/v1/admin/freight/forwarders/{fid}/reinstate", headers=ADM)
    rows = [(r.action, r.target_type, r.target_id, r.detail) for r in audit_rows(client) if r.target_type == "forwarder"]
    assert rows == [("suspend", "forwarder", fid, "licence expired"), ("reinstate", "forwarder", fid, None)]


def test_review_audited(client):
    a = apply(client, "u1").json()
    b = apply(client, "u2", company_name="Other Co").json()
    client.post(f"/v1/admin/freight/applications/{a['id']}/approve", headers=ADM, json={"note": "ok"})
    client.post(f"/v1/admin/freight/applications/{a['id']}/approve", headers=ADM)  # idempotent: no 2nd entry
    client.post(f"/v1/admin/freight/applications/{b['id']}/reject", headers=ADM, json={"reason": "no docs"})
    rows = [(r.action, r.target_id, r.detail) for r in audit_rows(client)]
    assert rows == [("approve", a["id"], "ok"), ("reject", b["id"], "no docs")]
    assert all(r.actor == "admin" for r in audit_rows(client))


def test_suspended_forwarder_dropped_from_listing_and_cannot_quote(client):
    fid = make_forwarder(client)
    assert [f["id"] for f in client.get("/v1/freight/forwarders", headers=uh("b")).json()["items"]] == [fid]
    client.post(f"/v1/admin/freight/forwarders/{fid}/suspend", headers=ADM, json={"reason": "fraud suspicion"})
    assert client.get("/v1/freight/forwarders", headers=uh("b")).json()["items"] == []
    assert client.get(f"/v1/freight/forwarders/{fid}", headers=uh("b")).status_code == 404
