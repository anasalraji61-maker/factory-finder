"""Private media: verification documents are never readable through the public route."""

import re
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import ALICE, BOB, solid, upload

ADMIN = {"X-Admin-Token": "adm-secret"}


@pytest.fixture
def c(make_client):
    return make_client(signing_key="k" * 32, admin_token="adm-secret")


def priv(c, seed=1, **kw):
    r = upload(c, solid(seed), kind=kw.pop("kind", "verification"), **kw)
    assert r.status_code == 201, r.text
    return r.json()


def signed(c, mid, headers=ALICE):
    r = c.post(f"/v1/media/files/{mid}/sign", headers=headers)
    return r


def path_q(url: str) -> str:
    p = urlsplit(url)
    return p.path + "?" + p.query


def test_verification_is_private_and_not_public(c):
    b = priv(c)
    assert b["visibility"] == "private" and b["kind"] == "verification" and b["widths"] == []
    assert re.fullmatch(r"/v1/media/private/[a-f0-9]{32}\.png", b["url"])  # relative, no query
    for ext in ("png", "jpg", "webp"):
        assert c.get(f"/v1/media/files/{b['id']}.{ext}").status_code == 404
        assert c.get(f"/v1/media/files/{b['id']}.{ext}", headers=ALICE).status_code == 404
        assert c.get(f"/v1/media/files/{b['id']}.{ext}?w=200").status_code in (404, 422)
    assert not [p for p in c.root.iterdir() if not p.name.startswith("p-")]  # only p- keys on disk


def test_visibility_field_and_validation(c):
    r = c.post("/v1/media/images", files={"file": ("a.png", solid(3), "image/png")}, data={"visibility": "private"}, headers=ALICE)
    assert r.status_code == 201 and r.json()["visibility"] == "private" and r.json()["kind"] == "listing"
    r = c.post("/v1/media/images", files={"file": ("a.png", solid(4), "image/png")}, data={"visibility": "secret"}, headers=ALICE)
    assert r.status_code == 422
    r = c.post("/v1/media/images", files={"file": ("a.png", solid(5), "image/png")}, data={"kind": "verification", "visibility": "public"}, headers=ALICE)
    assert r.status_code == 422
    r = c.post("/v1/media/images", files={"file": ("a.png", solid(6), "image/png")}, headers=ALICE)
    assert r.json()["visibility"] == "public"
    assert c.get(r.json()["url"].removeprefix("https://api.example.test")).status_code == 200  # public unchanged


def test_dedupe_does_not_cross_visibility(c):
    pub = upload(c, solid(7)).json()
    p = c.post("/v1/media/images", files={"file": ("a.png", solid(7), "image/png")}, data={"visibility": "private"}, headers=ALICE)
    assert p.status_code == 201 and p.json()["id"] != pub["id"] and p.json()["visibility"] == "private"
    again = c.post("/v1/media/images", files={"file": ("a.png", solid(7), "image/png")}, data={"visibility": "private"}, headers=ALICE)
    assert again.status_code == 200 and again.json()["id"] == p.json()["id"]
    assert c.get(f"/v1/media/files/{p.json()['id']}.png").status_code == 404


def test_owner_reads_directly_with_private_headers(c):
    b = priv(c)
    r = c.get(b["url"], headers=ALICE)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["x-content-type-options"] == "nosniff" and "etag" not in r.headers
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_authorization_matrix(c):
    b = priv(c)
    url = b["url"]
    assert c.get(url).status_code == 404  # anonymous, no signature
    assert c.get(url, headers=BOB).status_code == 404  # other user
    assert c.get(url, headers=ALICE).status_code == 200  # owner
    # sign: owner only
    assert signed(c, b["id"], BOB).status_code == 404
    assert c.post(f"/v1/media/files/{b['id']}/sign").status_code == 401
    assert signed(c, "0" * 32).status_code == 404
    assert c.post("/v1/media/files/not-an-id/sign", headers=ALICE).status_code == 404
    # public file cannot be signed
    pub = upload(c, solid(9)).json()
    assert signed(c, pub["id"]).status_code == 404
    # admin
    assert c.get(f"/v1/media/admin/files/{b['id']}").status_code == 401
    assert c.get(f"/v1/media/admin/files/{b['id']}", headers={"X-Admin-Token": "nope"}).status_code == 401
    assert c.get(f"/v1/media/admin/files/{b['id']}", headers={**ALICE}).status_code == 401
    r = c.get(f"/v1/media/admin/files/{b['id']}", headers=ADMIN)
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    assert c.get(f"/v1/media/admin/files/{b['id']}.png", headers=ADMIN).status_code == 200
    assert c.get(f"/v1/media/admin/files/{'0' * 32}", headers=ADMIN).status_code == 404
    assert c.get("/v1/media/admin/files/..%2fx", headers=ADMIN).status_code == 404


def test_admin_disabled_without_token(make_client):
    c = make_client(signing_key="k" * 32)
    b = priv(c)
    assert c.get(f"/v1/media/admin/files/{b['id']}", headers=ADMIN).status_code == 404


def test_signed_url_roundtrip_and_headers(c):
    b = priv(c)
    r = signed(c, b["id"])
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    body = r.json()
    assert body["ttl_seconds"] == 300
    q = parse_qs(urlsplit(body["url"]).query)
    assert q["u"] == ["alice"] and set(q) == {"u", "exp", "sig"}
    g = c.get(path_q(body["url"]))  # anonymous holder of the link
    assert g.status_code == 200 and g.headers["cache-control"] == "private, no-store"
    assert g.headers["x-content-type-options"] == "nosniff" and g.headers["referrer-policy"] == "no-referrer"


def test_signed_url_expiry(c, clock):
    b = priv(c)
    path = path_q(signed(c, b["id"]).json()["url"])
    clock.advance(seconds=299)
    assert c.get(path).status_code == 200
    clock.advance(seconds=2)
    assert c.get(path).status_code == 404


def test_tampered_signatures(c):
    a, b2 = priv(c, 1), priv(c, 2)
    q = parse_qs(urlsplit(signed(c, a["id"]).json()["url"]).query)
    u, exp, sig = q["u"][0], q["exp"][0], q["sig"][0]
    base = f"/v1/media/private/{a['id']}.png"
    assert c.get(f"{base}?u={u}&exp={exp}&sig={sig}").status_code == 200
    bad = [
        f"?u={u}&exp={exp}&sig={sig[:-1]}{'0' if sig[-1] != '0' else '1'}",
        f"?u={u}&exp={int(exp) + 1}&sig={sig}",  # extended expiry
        f"?u=bob&exp={exp}&sig={sig}",  # other user
        f"?u={u}&exp={exp}",  # no sig
        f"?exp={exp}&sig={sig}",  # no user
        f"?u={u}&sig={sig}",
        f"?u={u}&exp={exp}&sig=",
        f"?u={u}&exp={exp}&sig={'é' * 10}",  # non-ascii
        f"?u={u}&exp=abc&sig={sig}",
        f"?u={u}&exp=-5&sig={sig}",
        f"?u={u}&exp={10**15}&sig={sig}",
        f"?u={u}&exp={exp}&sig={sig.upper()}",
    ]
    for qs in bad:
        assert c.get(base + qs).status_code == 404, qs
    # signature for file A does not open file B (bound to file id), nor a wrong extension
    assert c.get(f"/v1/media/private/{b2['id']}.png?u={u}&exp={exp}&sig={sig}").status_code == 404
    assert c.get(f"/v1/media/private/{a['id']}.jpg?u={u}&exp={exp}&sig={sig}").status_code == 404
    # a valid link does not work for an authenticated stranger
    assert c.get(f"{base}?u={u}&exp={exp}&sig={sig}", headers=BOB).status_code == 404


def test_signature_with_other_key_rejected(make_client):
    one = make_client(signing_key="a" * 32)
    b = priv(one)
    path = path_q(signed(one, b["id"]).json()["url"])
    one.settings.signing_key = None
    svc = one.app.state.service
    svc.signing_key = b"b" * 32  # key rotated
    assert one.get(path).status_code == 404


def test_no_key_uses_random_process_key(make_client):
    c = make_client()
    b = priv(c)
    assert c.get(path_q(signed(c, b["id"]).json()["url"])).status_code == 200


def test_no_listing_and_no_leak_in_errors(c):
    priv(c)
    for p in ("/v1/media/private/", "/v1/media/private", "/v1/media/files/", "/v1/media/files", "/v1/media/admin/files/"):
        assert c.get(p, headers=ALICE).status_code in (404, 405)
    r = c.get(f"/v1/media/private/{'0' * 32}.png", headers=ALICE)
    assert r.status_code == 404 and "alice" not in r.text


def test_delete_removes_private_bytes(c):
    b = priv(c)
    assert c.delete(f"/v1/media/images/{b['id']}", headers=BOB).status_code == 404
    assert c.delete(f"/v1/media/images/{b['id']}", headers=ALICE).status_code == 204
    assert [p for p in c.root.rglob("*") if p.is_file()] == []
    assert c.get(f"/v1/media/admin/files/{b['id']}", headers=ADMIN).status_code == 404


def test_public_route_unchanged(c):
    b = upload(c, solid(11)).json()
    path = b["url"].removeprefix("https://api.example.test")
    r = c.get(path)
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert c.get(path, headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    assert c.get(f"/v1/media/private/{b['id']}.png").status_code == 404  # public files are not served on the private route
    assert c.get(f"/v1/media/private/{b['id']}.png", headers=ALICE).status_code == 404
