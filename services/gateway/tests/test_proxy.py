import httpx
import pytest

from ff_gateway.domain.routing import is_public, resolve_upstream


@pytest.mark.parametrize(
    ("path", "upstream"),
    [
        ("/v1/search", "sourcing"), ("/v1/listings/lst_1", "sourcing"), ("/v1/quotes/landed-cost", "logistics"), ("/v1/hs/851713", "logistics"),
        ("/v1/countries", "geo"), ("/v1/trust/suppliers/sup_1", "trust"), ("/v1/trust/suppliers:batch", "trust"),
        ("/v1/requests/req_1/offers", "rfq"), ("/v1/conversations", "messaging"), ("/v1/shipments", "tracking"),
        ("/v1/validate/container/X", "tracking"), ("/v1/watchlist", "notifications"), ("/v1/devices", "notifications"), ("/v1/notification-prefs", "notifications"), ("/v1/assistant/query", "assistant"),
        ("/v1/media/images", "media"), ("/v1/media/files/abc.jpg", "media"), ("/v1/mediax", None),
        ("/v1/invoices/inv_1/cancel", "payments"), ("/v1/ledger", "payments"), ("/v1/payments/webhooks/mock", "payments"),
        ("/v1/my/listings", "sourcing"), ("/v1/my/listings/nat_1/publish", "sourcing"), ("/v1/mything", None), ("/v1/suppliers/sup_1/reviews", "rfq"), ("/v1/suppliers/sup_1/review-summary", "rfq"), ("/v1/suppliers/sup_1", "sourcing"), ("/v1/suppliers/sup_1/reviews/x", "sourcing"), ("/v1/reviews/rev_1/reply", "rfq"), ("/v1/deals/deal_1/reviews", "rfq"), ("/v1/searchx", None), ("/v2/search", None), ("/v1/auth/login", None),
    ],
)  # fmt: skip
def test_resolve(path, upstream):
    assert resolve_upstream(path) == upstream


@pytest.mark.parametrize(
    ("method", "path", "public"),
    [
        ("GET", "/health", True), ("POST", "/v1/auth/login", True), ("GET", "/v1/search", True),
        ("GET", "/v1/fx/rates", True), ("GET", "/v1/hs/search", True), ("POST", "/v1/fx/convert", False), ("POST", "/v1/quotes/landed-cost", True),
        ("POST", "/v1/search", False), ("GET", "/v1/trust/suppliers/s", False), ("GET", "/v1/requests", False),
        ("GET", "/v1/sources", False), ("GET", "/v1/hubs/nearest", True), ("GET", "/v1/me", False), ("GET", "/v1/my/listings", False), ("POST", "/v1/my/listings", False),
        ("GET", "/v1/media/files/abc.jpg", True), ("HEAD", "/v1/media/files/abc.jpg", True), ("POST", "/v1/media/images", False),
        ("DELETE", "/v1/media/images/abc", False), ("POST", "/v1/media/files/abc.jpg", False), ("DELETE", "/v1/media/files/abc.jpg", False),
        ("GET", "/v1/media/images/abc", False),
        ("GET", "/v1/suppliers/s1/reviews", True), ("GET", "/v1/suppliers/s1/review-summary", True), ("POST", "/v1/suppliers/s1/reviews", False),
        ("POST", "/v1/deals/d1/reviews", False), ("PUT", "/v1/reviews/r1", False), ("DELETE", "/v1/reviews/r1", False), ("GET", "/v1/reviews/r1", False),
        ("POST", "/v1/reviews/r1/reply", False), ("POST", "/v1/reviews/r1/report", False), ("GET", "/v1/media/filesx", False),
    ],
)  # fmt: skip
def test_public_policy(method, path, public):
    assert is_public(method, path) is public


def test_public_route_proxied_without_token(client, mock_upstream):
    route = mock_upstream.get("http://localhost:8101/v1/search").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    r = client.get("/v1/search?q=pump&q=valve&page=2")
    assert r.status_code == 200 and r.json() == {"items": []}
    req = route.calls.last.request
    assert req.url.params.get_list("q") == ["pump", "valve"] and req.url.params["page"] == "2"
    assert "x-user-id" not in req.headers and req.headers["x-request-id"]


def test_protected_requires_token(client, mock_upstream):
    route = mock_upstream.get("http://localhost:8104/v1/trust/suppliers/sup_1").mock(
        return_value=httpx.Response(200, json={})
    )
    r = client.get("/v1/trust/suppliers/sup_1")
    assert r.status_code == 401 and not route.called
    assert client.post("/v1/search", json={}).status_code == 401  # only GET search is public


def test_header_injection_and_spoof_protection(make_client, mock_upstream, auth):
    c = make_client(internal_token="int-secret")
    tok = c.post(
        "/v1/auth/register", json={"email": "z@example.com", "password": "password123", "name": "Z"}
    ).json()
    route = mock_upstream.post("http://localhost:8105/v1/requests").mock(
        return_value=httpx.Response(201, json={"id": "req_1"}, headers={"X-Secret": "no"})
    )
    r = c.post(
        "/v1/requests", json={"title": "t"},
        headers={"Authorization": f"Bearer {tok['access_token']}", "X-User-Id": "usr_evil", "X-Internal-Token": "evil", "X-Request-Id": "rid-123"},
    )  # fmt: skip
    assert r.status_code == 201 and r.json() == {"id": "req_1"}
    assert r.headers["x-request-id"] == "rid-123" and "x-secret" not in r.headers
    req = route.calls.last.request
    assert req.headers["x-user-id"] == tok["user"]["id"]
    assert req.headers["x-internal-token"] == "int-secret"
    assert req.headers["x-request-id"] == "rid-123"
    assert "authorization" not in req.headers
    assert req.content == b'{"title":"t"}' or b'"title"' in req.content


def test_upstream_status_passthrough(client, hdr, mock_upstream):
    mock_upstream.get("http://localhost:8105/v1/requests/req_9").mock(
        return_value=httpx.Response(
            404, json={"error": {"code": "not_found", "message": "x", "details": {}}}
        )
    )
    r = client.get("/v1/requests/req_9", headers=hdr)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_upstream_down_502(client, hdr, mock_upstream):
    mock_upstream.get("http://localhost:8105/v1/requests").mock(
        side_effect=httpx.ConnectError("refused")
    )
    r = client.get("/v1/requests", headers=hdr)
    assert r.status_code == 502
    err = r.json()["error"]
    assert err["code"] == "upstream_unavailable" and err["details"]["upstream"] == "rfq"


def test_upstream_timeout_504(client, hdr, mock_upstream):
    mock_upstream.get("http://localhost:8106/v1/conversations").mock(
        side_effect=httpx.ReadTimeout("slow")
    )
    assert client.get("/v1/conversations", headers=hdr).status_code == 504


def test_custom_upstream_map(make_client, mock_upstream):
    c = make_client(upstreams={"trust": "http://trust.internal:9000"})
    tok = c.post(
        "/v1/auth/register", json={"email": "q@example.com", "password": "password123", "name": "Q"}
    ).json()
    route = mock_upstream.get("http://trust.internal:9000/v1/trust/evaluate").mock(
        return_value=httpx.Response(200, json={"ok": 1})
    )
    assert (
        c.get(
            "/v1/trust/evaluate", headers={"Authorization": f"Bearer {tok['access_token']}"}
        ).status_code
        == 200
    )
    assert route.called


def test_unknown_route_404_standard_body(client):
    r = client.get("/v1/nothing")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_request_id_cors_and_rate_limit(make_client, mock_upstream):
    c = make_client(rate_limit_per_minute=3)
    mock_upstream.get("http://localhost:8103/v1/countries").mock(
        return_value=httpx.Response(200, json=[])
    )
    r = c.get("/health", headers={"Origin": "http://app.example"})
    assert r.headers["x-request-id"] and "access-control-allow-origin" not in r.headers
    codes = [c.get("/v1/countries").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    limited = c.get("/v1/countries")
    assert limited.json()["error"]["code"] == "rate_limited" and "retry-after" in limited.headers
    assert c.get("/health").status_code == 200  # health exempt


def test_rate_limit_window_resets(make_client, clock, mock_upstream):
    c = make_client(auth_rate_limit_per_minute=2)
    body = {"email": "x@example.com", "password": "whatever1"}
    assert [c.post("/v1/auth/login", json=body).status_code for _ in range(3)] == [401, 401, 429]
    clock.advance(61)
    assert c.post("/v1/auth/login", json=body).status_code == 401


def test_home_http_client_partial_failure(make_client, mock_upstream):
    import httpx as hx
    from fastapi.testclient import TestClient

    from ff_gateway.config import Settings
    from ff_gateway.main import create_app

    app = create_app(
        Settings(
            jwt_secret="s" * 40,
            database_url="sqlite+aiosqlite://",
            bcrypt_rounds=4,
            home_client="http",
        ),
        http_client=hx.AsyncClient(),
    )
    mock_upstream.get("http://localhost:8101/v1/categories").mock(
        return_value=hx.Response(200, json=[{"id": "c"}])
    )
    mock_upstream.get("http://localhost:8101/v1/search").mock(
        return_value=hx.Response(200, json={"items": [{"id": "lst_1"}]})
    )
    mock_upstream.get("http://localhost:8102/v1/fx/rates").mock(side_effect=hx.ConnectError("down"))
    with TestClient(app) as c:
        tok = c.post(
            "/v1/auth/register",
            json={"email": "h@example.com", "password": "password123", "name": "H"},
        ).json()
        r = c.get("/v1/home", headers={"Authorization": f"Bearer {tok['access_token']}"})
    body = r.json()
    assert r.status_code == 200 and body["trending"] == [{"id": "lst_1"}] and body["fx"] is None
    assert body["warnings"] == [{"section": "fx", "message": "section unavailable"}]


def test_supplier_header_only_from_verified_claim(client, hdr, mock_upstream):
    route = mock_upstream.get("http://localhost:8106/v1/conversations").mock(
        return_value=httpx.Response(200, json={})
    )
    client.get("/v1/conversations", headers={**hdr, "X-Supplier-Id": "sup_evil"})
    assert "x-supplier-id" not in route.calls.last.request.headers
    client.patch("/v1/me", headers=hdr, json={"supplier_id": "sup_cn_018"})
    client.get("/v1/conversations", headers={**hdr, "X-Supplier-Id": "sup_evil"})
    assert "x-supplier-id" not in route.calls.last.request.headers  # pending claim is not trusted
    uid = client.get("/v1/me", headers=hdr).json()["id"]
    client.app.state.settings.admin_token = "adm"
    assert (
        client.post(
            f"/v1/admin/supplier-claims/{uid}/approve", headers={"X-Admin-Token": "adm"}
        ).status_code
        == 200
    )
    client.get("/v1/conversations", headers={**hdr, "X-Supplier-Id": "sup_evil"})
    assert route.calls.last.request.headers["x-supplier-id"] == "sup_cn_018"


def test_internal_only_route_not_exposed(client, mock_upstream, hdr):
    route = mock_upstream.post("http://localhost:8108/v1/alerts/evaluate").mock(
        return_value=httpx.Response(200, json={})
    )
    r = client.post("/v1/alerts/evaluate", headers=hdr, json={})
    assert r.status_code == 404 and not route.called


@pytest.mark.parametrize("path", [
    "/v1/internal/deals/deal_1/payment-status", "/v1/internal/deals/deal_1/payment-status/",
    "/v1/deals/../internal/deals/deal_1/payment-status", "/v1/internal",
])
def test_rfq_internal_payment_callback_is_never_reachable(client, mock_upstream, hdr, path):
    route = mock_upstream.post("http://localhost:8105/v1/internal/deals/deal_1/payment-status").mock(
        return_value=httpx.Response(200, json={})
    )
    for h in (hdr, {}):
        r = client.post(path, headers=h, json={"kind": "deal_payment", "status": "paid"})
        assert r.status_code in (400, 404), (path, r.status_code)
    assert not route.called


def test_deal_lifecycle_routes_are_proxied_to_rfq(client, mock_upstream, hdr):
    for sub in ("fulfilment/start", "delivered", "confirm-receipt"):
        route = mock_upstream.post(f"http://localhost:8105/v1/deals/deal_1/{sub}").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        assert client.post(f"/v1/deals/deal_1/{sub}", headers=hdr).status_code == 200 and route.called
        assert client.post(f"/v1/deals/deal_1/{sub}").status_code == 401


def test_deal_lookup_routes_are_proxied_authenticated(client, mock_upstream, hdr):
    for path in ("/v1/deals", "/v1/requests/req_1/deal"):
        route = mock_upstream.get(f"http://localhost:8105{path}").mock(return_value=httpx.Response(200, json={"items": []}))
        assert client.get(f"{path}?role=buyer&page=2", headers=hdr).status_code == 200 and route.called
        assert route.calls.last.request.url.query == b"role=buyer&page=2"
        assert client.get(path).status_code == 401


def test_cors_default_denies_and_env_allows(make_client):
    c = make_client()
    r = c.options(
        "/v1/countries",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in r.headers
    c2 = make_client(cors_origins=["http://localhost:3000"])
    ok = c2.get("/health", headers={"Origin": "http://localhost:3000"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    bad = c2.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in bad.headers


def test_rfq_gets_verified_supplier_header_only(client, auth, hdr, mock_upstream):
    route = mock_upstream.post("http://localhost:8105/v1/requests/req_1/offers").mock(
        return_value=httpx.Response(201, json={})
    )
    client.post("/v1/requests/req_1/offers", json={}, headers={**hdr, "X-Supplier-Id": "sup_spoof"})
    assert "x-supplier-id" not in route.calls.last.request.headers


def _sourcing_my_upstream(mock_upstream):
    """Stand-in for sourcing: 403 unless the (gateway-set) X-Supplier-Id header is present."""

    def reply(request):
        sid = request.headers.get("x-supplier-id")
        if not sid:
            return httpx.Response(403, json={"error": {"code": "supplier_required", "message": "m"}})
        return httpx.Response(200, json={"items": [], "supplier": sid})

    return mock_upstream.get("http://localhost:8101/v1/my/listings").mock(side_effect=reply)


def test_my_listings_requires_login(client, mock_upstream):
    route = _sourcing_my_upstream(mock_upstream)
    assert client.get("/v1/my/listings").status_code == 401 and not route.called


def test_my_listings_supplier_header_only_from_verified_claim(client, hdr, mock_upstream):
    route = _sourcing_my_upstream(mock_upstream)
    spoof = {**hdr, "X-Supplier-Id": "sup_evil"}
    r = client.get("/v1/my/listings", headers=spoof)  # no claim: spoofed header is dropped
    assert r.status_code == 403 and "x-supplier-id" not in route.calls.last.request.headers
    client.patch("/v1/me", headers=hdr, json={"supplier_id": "sup_cn_018"})
    r = client.get("/v1/my/listings", headers=spoof)  # claim still unverified
    assert r.status_code == 403 and "x-supplier-id" not in route.calls.last.request.headers
    uid = client.get("/v1/me", headers=hdr).json()["id"]
    client.app.state.settings.admin_token = "adm"
    client.post(f"/v1/admin/supplier-claims/{uid}/approve", headers={"X-Admin-Token": "adm"})
    r = client.get("/v1/my/listings", headers=spoof)  # verified: header comes from our DB
    assert r.status_code == 200 and r.json()["supplier"] == "sup_cn_018"
    assert route.calls.last.request.headers["x-supplier-id"] == "sup_cn_018"


def test_public_sourcing_routes_do_not_get_supplier_header(client, hdr, mock_upstream):
    route = mock_upstream.get("http://localhost:8101/v1/search").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    client.get("/v1/search", headers=hdr)
    assert "x-supplier-id" not in route.calls.last.request.headers


def test_media_upload_requires_auth_and_forwards_multipart(make_client, mock_upstream):
    c = make_client(internal_token="int-secret")
    tok = c.post("/v1/auth/register", json={"email": "m@example.com", "password": "password123", "name": "M"}).json()
    route = mock_upstream.post("http://localhost:8112/v1/media/images").mock(
        return_value=httpx.Response(201, json={"id": "a" * 32})
    )
    files = {"file": ("p.png", b"\x89PNG-bytes", "image/png")}
    assert c.post("/v1/media/images", files=files).status_code == 401 and not route.called
    r = c.post(
        "/v1/media/images", files=files, data={"kind": "avatar"},
        headers={"Authorization": f"Bearer {tok['access_token']}", "X-User-Id": "usr_evil"},
    )
    assert r.status_code == 201
    req = route.calls.last.request
    assert req.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert req.headers["x-user-id"] == tok["user"]["id"] and req.headers["x-internal-token"] == "int-secret"
    assert b"\x89PNG-bytes" in req.content and b'name="kind"' in req.content


def test_media_delete_requires_auth(client, hdr, mock_upstream):
    route = mock_upstream.delete(f"http://localhost:8112/v1/media/images/{'a' * 32}").mock(return_value=httpx.Response(204))
    assert client.delete(f"/v1/media/images/{'a' * 32}").status_code == 401 and not route.called
    assert client.delete(f"/v1/media/images/{'a' * 32}", headers=hdr).status_code == 204 and route.called


def test_media_files_public_binary_and_security_headers_pass_through(client, mock_upstream):
    png = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
    route = mock_upstream.get(f"http://localhost:8112/v1/media/files/{'a' * 32}.png").mock(
        return_value=httpx.Response(
            200, content=png,
            headers={"Content-Type": "image/png", "Cache-Control": "public, max-age=31536000, immutable",
                     "X-Content-Type-Options": "nosniff", "ETag": '"e1"', "Set-Cookie": "no=1"},
        )
    )
    r = client.get(f"/v1/media/files/{'a' * 32}.png?w=200")  # no token
    assert r.status_code == 200 and r.content == png
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["content-type"] == "image/png"
    assert "immutable" in r.headers["cache-control"] and r.headers["etag"] == '"e1"' and "set-cookie" not in r.headers
    req = route.calls.last.request
    assert req.url.params["w"] == "200" and "x-user-id" not in req.headers


def test_media_traversal_is_rejected_at_gateway(client, mock_upstream):
    route = mock_upstream.get(url__regex=r"http://localhost:8112/.*").mock(return_value=httpx.Response(200))
    assert client.get("/v1/media/files/../../auth/me").status_code in (400, 404, 401)
    assert not route.called


def test_public_image_reads_have_their_own_rate_bucket(make_client, mock_upstream):
    c = make_client(rate_limit_per_minute=2, media_rate_limit_per_minute=5)
    mock_upstream.get(url__regex=r"http://localhost:8112/v1/media/files/.*").mock(
        return_value=httpx.Response(200, content=b"x", headers={"content-type": "image/png"})
    )
    mock_upstream.get("http://localhost:8103/v1/countries").mock(
        return_value=httpx.Response(200, json=[])
    )
    media = [c.get("/v1/media/files/" + "a" * 32 + ".png").status_code for _ in range(6)]
    assert media[:5] == [200] * 5 and media[5] == 429
    # the ordinary API bucket is untouched by image traffic
    assert c.get("/v1/countries").status_code == 200


def test_supplier_reviews_public_get_goes_to_rfq(client, mock_upstream):
    route = mock_upstream.get("http://localhost:8105/v1/suppliers/sup_1/reviews").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    summ = mock_upstream.get("http://localhost:8105/v1/suppliers/sup_1/review-summary").mock(
        return_value=httpx.Response(200, json={"count": 0})
    )
    assert client.get("/v1/suppliers/sup_1/reviews?page=2&sort=rating").status_code == 200
    assert route.calls.last.request.url.params["sort"] == "rating"
    assert "x-user-id" not in route.calls.last.request.headers
    assert client.get("/v1/suppliers/sup_1/review-summary").status_code == 200 and summ.called


def test_review_writes_need_auth_and_get_reviewer_name(client, auth, hdr, mock_upstream):
    route = mock_upstream.post("http://localhost:8105/v1/deals/deal_1/reviews").mock(
        return_value=httpx.Response(201, json={})
    )
    assert client.post("/v1/deals/deal_1/reviews", json={"rating": 5}).status_code == 401
    assert not route.called
    client.post("/v1/deals/deal_1/reviews", json={"rating": 5}, headers={**hdr, "X-User-Name": "evil"})
    assert route.calls.last.request.headers["x-user-name"] == "Anas"
