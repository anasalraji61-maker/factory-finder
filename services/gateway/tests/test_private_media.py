import httpx
import pytest

M = "http://localhost:8112"
FID = "a" * 32
H = {"X-Admin-Token": "adm"}


def _c(make_client, **kw):
    return make_client(admin_token="adm", internal_token="int", media_admin_token="med-adm", **kw)


def test_admin_passthrough_injects_and_hardens(make_client, mock_upstream):
    c = _c(make_client)
    route = mock_upstream.get(f"{M}/v1/media/admin/files/{FID}.png").mock(
        return_value=httpx.Response(200, content=b"PNGDATA", headers={"content-type": "image/png", "cache-control": "private, no-store", "x-content-type-options": "nosniff", "set-cookie": "x=1"})
    )
    assert c.get(f"/v1/admin/media/files/{FID}.png").status_code == 401
    assert c.get(f"/v1/admin/media/files/{FID}.png", headers={"X-Admin-Token": "bad"}).status_code == 401
    assert not route.called
    r = c.get(f"/v1/admin/media/files/{FID}.png", headers={**H, "X-User-Id": "evil", "Authorization": "Bearer x"})
    assert r.status_code == 200 and r.content == b"PNGDATA"
    assert r.headers["cache-control"] == "private, no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert "set-cookie" not in r.headers
    h = route.calls.last.request.headers
    assert h["x-admin-token"] == "med-adm" and h["x-internal-token"] == "int" and h["x-user-id"] == "admin"
    assert "authorization" not in h


def test_admin_passthrough_disabled_and_strict(make_client, mock_upstream):
    c = make_client(internal_token="int", media_admin_token="m")
    assert c.get(f"/v1/admin/media/files/{FID}", headers=H).status_code == 404  # no gateway admin token
    c = make_client(admin_token="adm")
    assert c.get(f"/v1/admin/media/files/{FID}", headers=H).status_code == 404  # no media admin token
    c = _c(make_client)
    for bad in ("short", "A" * 32, f"{FID}.gif", f"{FID}.png.x", "..%2f..%2fx"):
        assert c.get(f"/v1/admin/media/files/{bad}", headers=H).status_code in (400, 404)
    assert c.get(f"/v1/admin/media/files/{FID}?x=1", headers=H).status_code == 404
    assert c.post(f"/v1/admin/media/files/{FID}", headers=H).status_code in (404, 405)


def test_media_admin_route_not_reachable_via_proxy(make_client, mock_upstream, hdr):
    c = _c(make_client)
    route = mock_upstream.get(url__regex=r"http://localhost:8112/.*").mock(return_value=httpx.Response(200, content=b"x"))
    r = c.get(f"/v1/media/admin/files/{FID}.png", headers={"X-Admin-Token": "med-adm"})
    assert r.status_code == 404 and not route.called


def test_sign_requires_login_and_forwards_identity(client, mock_upstream, hdr):
    route = mock_upstream.post(f"{M}/v1/media/files/{FID}/sign").mock(
        return_value=httpx.Response(200, json={"url": "/v1/media/private/x", "expires_at": "2026-10-15T00:00:00Z", "ttl_seconds": 300})
    )
    assert client.post(f"/v1/media/files/{FID}/sign").status_code == 401
    assert not route.called
    r = client.post(f"/v1/media/files/{FID}/sign", headers={**hdr, "X-User-Id": "evil"})
    assert r.status_code == 200
    assert route.calls.last.request.headers["x-user-id"] != "evil"


def test_private_route_is_public_but_forwards_identity_only_from_token(client, mock_upstream, hdr):
    route = mock_upstream.get(url__regex=r"http://localhost:8112/v1/media/private/.*").mock(
        return_value=httpx.Response(200, content=b"img", headers={"cache-control": "private, no-store", "x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "etag": '"x"'})
    )
    r = client.get(f"/v1/media/private/{FID}.png?u=alice&exp=9999999999&sig=abc", headers={"X-User-Id": "evil"})
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store" and r.headers["referrer-policy"] == "no-referrer"
    req = route.calls.last.request
    assert "x-user-id" not in req.headers and dict(req.url.params) == {"u": "alice", "exp": "9999999999", "sig": "abc"}
    client.get(f"/v1/media/private/{FID}.png", headers=hdr)
    assert route.calls.last.request.headers["x-user-id"] not in ("", "evil")
    client.get(f"/v1/media/private/{FID}.png", headers={"Authorization": "Bearer junk"})  # bad token = anonymous
    assert "x-user-id" not in route.calls.last.request.headers


def test_private_reads_are_media_rate_limited(make_client, mock_upstream):
    c = make_client(media_rate_limit_per_minute=3)
    mock_upstream.get(url__regex=r"http://localhost:8112/v1/media/private/.*").mock(return_value=httpx.Response(404, json={}))
    codes = [c.get(f"/v1/media/private/{FID}.png").status_code for _ in range(5)]
    assert codes[:3] == [404] * 3 and 429 in codes[3:]


@pytest.mark.parametrize("method", ["POST", "DELETE", "PUT"])
def test_private_prefix_is_get_only_public(client, method):
    assert client.request(method, f"/v1/media/private/{FID}.png").status_code == 401
