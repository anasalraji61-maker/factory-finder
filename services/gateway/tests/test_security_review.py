import httpx


def test_admin_token_is_never_forwarded_and_admin_paths_are_rate_limited(make_client, mock_upstream):
    c = make_client(admin_token="adm", admin_fail_limit_per_minute=5)
    tok = c.post("/v1/auth/register", json={"email": "q@example.com", "password": "password123", "name": "Q"}).json()
    base = c.app.state.settings.upstream_map()["payments"].rstrip("/")
    route = mock_upstream.post(f"{base}/v1/payments/sweep").mock(return_value=httpx.Response(403, json={}))
    c.post("/v1/payments/sweep", headers={"Authorization": f"Bearer {tok['access_token']}", "X-Admin-Token": "adm"})
    assert "x-admin-token" not in route.calls.last.request.headers
    codes = [c.get("/v1/admin/supplier-claims", headers={"X-Admin-Token": f"guess{i}"}).status_code for i in range(12)]
    assert 429 in codes  # admin-token guessing is throttled like auth


def _raw(client, method, path, headers=()):
    """Send a request whose path is NOT normalised by a client (like curl --path-as-is)."""
    app, out = client.app, {}

    async def run():
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "path": path,
            "raw_path": path.encode(), "query_string": b"", "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
            "client": ("203.0.113.9", 1234), "server": ("testserver", 80), "scheme": "http", "root_path": "",
        }  # fmt: skip
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        async def send(msg):
            if msg["type"] == "http.response.start":
                out["status"] = msg["status"]

        await app(scope, receive, send)

    client.portal.call(run)  # the app's own event loop: a fresh asyncio.run() loop left pooled DB connections on a closed loop (teardown flake)
    return out["status"]


def test_dot_segments_cannot_sidestep_path_policies(client, hdr):
    """httpx collapses '/./' upstream, so '/v1/alerts/./evaluate' used to skip the exact-match internal-only block."""
    h = [("authorization", hdr["Authorization"])]
    for p in ("/v1/alerts/./evaluate", "/v1/feed/./posts", "/v1/trust/./verification/documents", "/v1/alerts/../alerts/evaluate"):
        assert _raw(client, "POST", p, h) == 400, p

def test_path_tricks_are_refused(client, hdr):
    """Review e: empty segments, backslashes and still-encoded dots/slashes could be normalised differently upstream."""
    h = [("authorization", hdr["Authorization"])]
    for p in (
        "/v1/alerts//evaluate", "//v1/alerts/evaluate", "/v1/alerts/%2e/evaluate", "/v1/alerts/%2E%2e/evaluate",
        "/v1/alerts%2fevaluate", "/v1/alerts\\evaluate", "/v1/media/files/%5c..%5cprivate",
    ):
        assert _raw(client, "POST", p, h) == 400, p
    assert _raw(client, "GET", "/v1/media/files/", h) != 400  # one trailing slash stays legal


def test_admin_failed_attempts_throttled_at_20_per_minute_by_default(make_client):
    c = make_client(admin_token="adm")
    codes = [c.get("/v1/admin/supplier-claims", headers={"X-Admin-Token": f"bad{i}"}).status_code for i in range(22)]
    assert codes[:20] == [401] * 20 and codes[20] == 429
    r = c.get("/v1/admin/supplier-claims", headers={"X-Admin-Token": "adm"})
    assert r.status_code == 429  # blocked even for the right token until the window passes
    assert r.headers["cache-control"] == "no-store"


def test_admin_responses_are_no_store_and_404_when_unset(make_client):
    off = make_client()
    r = off.get("/v1/admin/supplier-claims", headers={"X-Admin-Token": "x"})
    assert r.status_code == 404 and r.headers["cache-control"] == "no-store"
    on = make_client(admin_token="adm")
    for h in ({}, {"X-Admin-Token": "nope"}, {"X-Admin-Token": "adm"}):
        r = on.get("/v1/admin/supplier-claims", headers=h)
        assert r.headers["cache-control"] == "no-store"


def test_admin_token_never_logged(make_client, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    c = make_client(admin_token="s3cret-admin-value")
    c.get("/v1/admin/supplier-claims", headers={"X-Admin-Token": "wrong-guess-zzz", "X-Reviewer": "a@b.c\nx"})
    c.get("/v1/admin/supplier-claims", headers={"X-Admin-Token": "s3cret-admin-value"})
    assert "s3cret-admin-value" not in caplog.text and "wrong-guess-zzz" not in caplog.text
