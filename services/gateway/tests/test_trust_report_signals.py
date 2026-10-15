import httpx

URL = "http://localhost:8104/v1/trust/suppliers/sup_1/report"
SPOOF = {"X-Account-Age-Seconds": "99999999", "X-Email-Verified": "1"}


def _reg(c, email):
    return c.post("/v1/auth/register", json={"email": email, "password": "password123", "name": "R"}).json()["access_token"]


def test_report_gets_account_age_and_unverified_from_user_record_not_client(make_client, mock_upstream, clock):
    c = make_client(internal_token="int-secret")
    route = mock_upstream.post(URL).mock(return_value=httpx.Response(201, json={}))
    tok = _reg(c, "r1@example.com")
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from ff_gateway.db import User

    async def _age():
        async with c.app.state.sessionmaker() as s:
            await s.execute(update(User).where(User.email == "r1@example.com").values(created_at=datetime.now(UTC) - timedelta(hours=1)))
            await s.commit()

    c.portal.call(_age)
    r = c.post("/v1/trust/suppliers/sup_1/report", json={"type": "fraud", "text": "x"}, headers={"Authorization": f"Bearer {tok}", **SPOOF})
    assert r.status_code == 201
    sent = route.calls.last.request.headers
    assert sent["x-email-verified"] == "0" and 3600 <= int(sent["x-account-age-seconds"]) < 3700
    assert sent["x-internal-token"] == "int-secret"


def test_signals_only_on_report_posts_and_client_values_stripped(make_client, mock_upstream):
    c = make_client()
    route = mock_upstream.get("http://localhost:8104/v1/trust/suppliers/sup_1").mock(return_value=httpx.Response(200, json={}))
    tok = _reg(c, "r2@example.com")
    assert c.get("/v1/trust/suppliers/sup_1", headers={"Authorization": f"Bearer {tok}", **SPOOF}).status_code == 200
    sent = route.calls.last.request.headers
    assert "x-account-age-seconds" not in sent and "x-email-verified" not in sent


def test_verified_email_is_forwarded_as_verified(make_client, mock_upstream, clock):
    import asyncio

    from ff_gateway.db import User
    c = make_client()
    route = mock_upstream.post(URL).mock(return_value=httpx.Response(201, json={}))
    tok = _reg(c, "r3@example.com")

    async def _verify():
        async with c.app.state.sessionmaker() as s:
            from sqlalchemy import select
            u = (await s.execute(select(User).where(User.email == "r3@example.com"))).scalar_one()
            u.email_verified = True
            await s.commit()

    c.portal.call(_verify) if getattr(c, "portal", None) else asyncio.run(_verify())
    assert c.post("/v1/trust/suppliers/sup_1/report", json={"type": "fraud", "text": "x"}, headers={"Authorization": f"Bearer {tok}"}).status_code == 201
    assert route.calls.last.request.headers["x-email-verified"] == "1"
