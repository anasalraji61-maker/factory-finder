import re
import statistics
import time

from sqlalchemy import select

from ff_gateway.db import PasswordResetToken

REG = {"email": "p@example.com", "password": "password123", "name": "P"}
NEW = "n3w-Secret-pass"


def _mk(make_client, **kw):
    kw.setdefault("mail_backend", "mock")
    kw.setdefault("auth_rate_limit_per_minute", 1000)
    return make_client(**kw)


def _forgot(c, email=REG["email"]):
    return c.post("/v1/auth/password/forgot", json={"email": email})


def _code(c):
    mails = [m for m in c.app.state.mailer.outbox if m.subject == "Reset your password"]
    return re.search(r"Reset code: (\S+)", mails[-1].body).group(1), len(mails)


def _reset(c, token, pw=NEW):
    return c.post("/v1/auth/password/reset", json={"token": token, "new_password": pw})


def _login(c, pw):
    return c.post("/v1/auth/login", json={"email": REG["email"], "password": pw})


def test_forgot_identical_for_known_and_unknown(make_client):
    c = _mk(make_client)
    c.post("/v1/auth/register", json=REG)
    known, unknown = _forgot(c), _forgot(c, "ghost@example.com")
    assert known.status_code == unknown.status_code == 202
    assert known.content == unknown.content and known.json() == {"status": "accepted"}
    assert {
        k: v for k, v in known.headers.items() if k in ("content-type", "content-length", "cache-control")
    } == {k: v for k, v in unknown.headers.items() if k in ("content-type", "content-length", "cache-control")}
    assert _code(c)[1] == 1  # only the real account got mail
    assert [m.to for m in c.app.state.mailer.outbox if m.subject == "Reset your password"] == [REG["email"]]


def test_forgot_timing_does_not_reveal_account(make_client):
    c = _mk(make_client, password_forgot_per_minute=1000, password_forgot_per_email_per_minute=1000)
    c.post("/v1/auth/register", json=REG)

    def t(email):
        out = []
        for _ in range(7):
            a = time.perf_counter()
            assert _forgot(c, email).status_code == 202
            out.append(time.perf_counter() - a)
        return statistics.median(out)

    t(REG["email"])  # warm up
    known, unknown = t(REG["email"]), t("ghost@example.com")
    assert abs(known - unknown) < 0.05  # no bcrypt / per-account work on the request path


def test_forgot_mail_off_is_silent_noop(make_client):
    c = make_client(mail_backend="off")
    c.post("/v1/auth/register", json=REG)
    r = _forgot(c)
    assert r.status_code == 202 and r.json() == {"status": "accepted"}


def test_forgot_throttled_silently(make_client):
    c = _mk(make_client)
    c.post("/v1/auth/register", json=REG)
    first, second = _forgot(c), _forgot(c)  # second hit is throttled per email+IP
    assert first.content == second.content and second.status_code == 202
    assert _code(c)[1] == 1


def test_forgot_per_email_cap_across_ips(make_client):
    c = _mk(make_client, password_forgot_per_minute=100, password_forgot_per_email_per_minute=2)
    c.post("/v1/auth/register", json=REG)
    for _ in range(5):
        assert _forgot(c).status_code == 202
    assert _code(c)[1] == 2


def test_forgot_validation_and_ip_limit(make_client):
    c = _mk(make_client, auth_rate_limit_per_minute=3)
    assert _forgot(c, "not-an-email").status_code == 422
    assert [_forgot(c, f"x{i}@example.com").status_code for i in range(3)][-1] == 429  # IP limit still applies


def test_reset_flow_single_use_and_revokes_sessions(make_client):
    c = _mk(make_client)
    tok = c.post("/v1/auth/register", json=REG).json()
    other = _login(c, REG["password"]).json()
    _forgot(c)
    code, _ = _code(c)
    assert _reset(c, code).status_code == 204
    assert _reset(c, code, "an0ther-Pass-x").status_code == 400  # reuse
    assert _login(c, REG["password"]).status_code == 401
    assert _login(c, NEW).status_code == 200
    for t in (tok, other):  # every refresh token of the user is dead
        assert c.post("/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_reset_token_hashed_at_rest_and_expires(make_client, clock):
    c = _mk(make_client, password_reset_ttl_seconds=1800)
    c.post("/v1/auth/register", json=REG)
    _forgot(c)
    code, _ = _code(c)

    async def rows():
        async with c.app.state.sessionmaker() as s:
            return (await s.scalars(select(PasswordResetToken))).all()

    rs = c.portal.call(rows)
    assert len(rs) == 1 and rs[0].token_hash != code and len(rs[0].token_hash) == 64
    clock.advance(1799)
    # still valid just before expiry? verify via a second token at the boundary below
    clock.advance(2)
    r = _reset(c, code)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_reset_token"
    assert _login(c, REG["password"]).status_code == 200  # password untouched


def test_reset_valid_within_ttl(make_client, clock):
    c = _mk(make_client)
    c.post("/v1/auth/register", json=REG)
    _forgot(c)
    code, _ = _code(c)
    clock.advance(29 * 60)
    assert _reset(c, code).status_code == 204


def test_reset_unknown_token_generic_and_policy_keeps_token(make_client):
    c = _mk(make_client)
    c.post("/v1/auth/register", json=REG)
    assert _reset(c, "x" * 30).status_code == 400
    _forgot(c)
    code, _ = _code(c)
    assert _reset(c, code, "password").status_code == 422  # policy (deny-list)
    assert _reset(c, code, "p@example.com").status_code == 422  # equals the email
    assert _reset(c, code, "short").status_code == 422
    assert _reset(c, code).status_code == 204  # token survived the rejected attempts


def test_new_forgot_invalidates_previous_token(make_client, clock):
    c = _mk(make_client, password_forgot_per_minute=1)
    c.post("/v1/auth/register", json=REG)
    _forgot(c)
    old, _ = _code(c)
    clock.advance(61)
    _forgot(c)
    new, n = _code(c)
    assert n == 2 and old != new
    assert _reset(c, old).status_code == 400
    assert _reset(c, new).status_code == 204


def test_reset_for_disabled_account_refused(make_client):
    from sqlalchemy import update

    from ff_gateway.db import User

    c = _mk(make_client)
    c.post("/v1/auth/register", json=REG)
    _forgot(c)
    code, _ = _code(c)

    async def disable():
        async with c.app.state.sessionmaker() as s:
            await s.execute(update(User).values(is_active=False))
            await s.commit()

    c.portal.call(disable)
    assert _reset(c, code).status_code == 400


# ---- POST /v1/me/password ----

def _hdr(tok):
    return {"Authorization": f"Bearer {tok['access_token']}"}


def test_change_password_revokes_other_sessions(make_client):
    c = _mk(make_client)
    tok = c.post("/v1/auth/register", json=REG).json()
    other = _login(c, REG["password"]).json()
    r = c.post("/v1/me/password", headers=_hdr(tok), json={"current_password": REG["password"], "new_password": NEW})
    assert r.status_code == 200
    fresh = r.json()
    assert c.post("/v1/auth/refresh", json={"refresh_token": other["refresh_token"]}).status_code == 401
    assert c.post("/v1/auth/refresh", json={"refresh_token": tok["refresh_token"]}).status_code == 401
    assert c.post("/v1/auth/refresh", json={"refresh_token": fresh["refresh_token"]}).status_code == 200
    assert _login(c, REG["password"]).status_code == 401 and _login(c, NEW).status_code == 200


def test_change_password_requires_auth_correct_current_and_policy(make_client):
    c = _mk(make_client)
    tok = c.post("/v1/auth/register", json=REG).json()
    body = {"current_password": REG["password"], "new_password": NEW}
    assert c.post("/v1/me/password", json=body).status_code == 401
    bad = c.post("/v1/me/password", headers=_hdr(tok), json={**body, "current_password": "wrong-password"})
    assert bad.status_code == 403 and bad.json()["error"]["code"] == "reauth_failed"
    assert c.post("/v1/me/password", headers=_hdr(tok), json={**body, "new_password": "password"}).status_code == 422
    same = c.post("/v1/me/password", headers=_hdr(tok), json={**body, "new_password": REG["password"]})
    assert same.status_code == 422
    assert _login(c, REG["password"]).status_code == 200  # nothing changed


def test_change_password_bruteforce_throttled(make_client):
    c = _mk(make_client, login_fail_limit_per_minute=3)
    tok = c.post("/v1/auth/register", json=REG).json()
    body = {"current_password": "guess-guess-1", "new_password": NEW}
    codes = [c.post("/v1/me/password", headers=_hdr(tok), json=body).status_code for _ in range(5)]
    assert codes[:3] == [403] * 3 and codes[3:] == [429, 429]
    ok = {"current_password": REG["password"], "new_password": NEW}
    assert c.post("/v1/me/password", headers=_hdr(tok), json=ok).status_code == 429  # even the right one while blocked


# ---- PATCH /v1/me email change re-auth ----

def test_email_change_requires_current_password(make_client):
    c = _mk(make_client)
    tok = c.post("/v1/auth/register", json=REG).json()
    h = _hdr(tok)
    assert c.patch("/v1/me", headers=h, json={"email": "new@example.com"}).status_code == 422
    r = c.patch("/v1/me", headers=h, json={"email": "new@example.com", "current_password": "nope-nope-1"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "reauth_failed"
    assert c.get("/v1/me", headers=h).json()["email"] == REG["email"]
    ok = c.patch("/v1/me", headers=h, json={"email": "new@example.com", "current_password": REG["password"]})
    assert ok.status_code == 200 and ok.json()["email"] == "new@example.com"
    assert "current_password" not in ok.json()


def test_other_fields_and_same_email_need_no_password(make_client):
    c = _mk(make_client)
    tok = c.post("/v1/auth/register", json=REG).json()
    h = _hdr(tok)
    assert c.patch("/v1/me", headers=h, json={"name": "Z"}).status_code == 200
    assert c.patch("/v1/me", headers=h, json={"email": REG["email"]}).status_code == 200
