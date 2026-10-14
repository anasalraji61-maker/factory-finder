import httpx


def test_admin_token_is_never_forwarded_and_admin_paths_are_rate_limited(make_client, mock_upstream):
    c = make_client(admin_token="adm", auth_rate_limit_per_minute=5)
    tok = c.post("/v1/auth/register", json={"email": "q@example.com", "password": "password123", "name": "Q"}).json()
    base = c.app.state.settings.upstream_map()["payments"].rstrip("/")
    route = mock_upstream.post(f"{base}/v1/payments/sweep").mock(return_value=httpx.Response(403, json={}))
    c.post("/v1/payments/sweep", headers={"Authorization": f"Bearer {tok['access_token']}", "X-Admin-Token": "adm"})
    assert "x-admin-token" not in route.calls.last.request.headers
    codes = [c.get("/v1/admin/supplier-claims", headers={"X-Admin-Token": f"guess{i}"}).status_code for i in range(12)]
    assert 429 in codes  # admin-token guessing is throttled like auth
