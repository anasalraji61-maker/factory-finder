"""Security review k: body caps must also hold for methods without a conventional body (GET/HEAD/OPTIONS)."""

import httpx
import respx


def test_get_with_oversized_body_is_refused_before_buffering(make_client):
    c = make_client(json_max_body_bytes=1000, max_body_bytes=5000)
    with respx.mock(assert_all_called=False) as m:
        route = m.get("http://localhost:8101/v1/search").mock(return_value=httpx.Response(200, json={}))
        r = c.request("GET", "/v1/search", content=b"x" * 3000)
        assert r.status_code == 413
        assert not route.called


def test_get_with_chunked_oversized_body_is_refused(make_client):
    c = make_client(json_max_body_bytes=1000)

    def gen():
        for _ in range(30):
            yield b"y" * 100

    r = c.request("GET", "/v1/search", content=gen())
    assert r.status_code == 413


def test_rate_limit_not_evadable_with_forged_xff(make_client):
    c = make_client(rate_limit_per_minute=3)
    codes = [c.get("/v1/nope", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(6)]
    assert 429 in codes


def test_client_internal_headers_never_forwarded(client, hdr):
    c = client
    with respx.mock(assert_all_called=False) as m:
        route = m.get("http://localhost:8101/v1/my/listings").mock(return_value=httpx.Response(200, json={}))
        sr = m.get("http://localhost:8101/v1/search").mock(return_value=httpx.Response(200, json={}))
        c.get("/v1/search", headers={"X-User-Id": "evil", "X-Internal-Token": "x", "X-Admin-Token": "y", "X-Supplier-Id": "s"})
        assert not {"x-admin-token", "x-supplier-id"} & set(sr.calls.last.request.headers)
        assert sr.calls.last.request.headers.get("x-user-id") != "evil"
        c.get("/v1/my/listings", headers={**hdr, "X-User-Id": "evil", "X-Admin-Token": "y", "X-Supplier-Id": "s", "X-Internal-Token": "x"})
        sent = route.calls.last.request.headers
        assert sent.get("x-user-id") != "evil" and "x-admin-token" not in sent and "x-supplier-id" not in sent
        assert sent.get("x-internal-token") != "x"
