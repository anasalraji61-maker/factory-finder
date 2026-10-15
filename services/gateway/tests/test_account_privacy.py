"""Account deletion (DELETE /v1/me) and privacy export (GET /v1/me/export): fan-out, partial failure, retry, authz."""

import json

import httpx
import pytest
from sqlalchemy import func, select

from ff_gateway.config import DEFAULT_UPSTREAMS
from ff_gateway.db import AccountEvent, DeletionJob, RefreshToken, User
from ff_gateway.domain import privacy

PORT_TO_SVC = {int(u.rsplit(":", 1)[1]): n for n, u in DEFAULT_UPSTREAMS.items()}
PW = "password123"


class Fleet:
    """Mock of every service's internal export/erase endpoints; per-service failures can be injected."""

    def __init__(self, mock):
        self.calls: list[tuple[str, str, str, dict]] = []  # (method, service, user_id, headers)
        self.fail: dict[str, object] = {}  # service -> status code | Exception
        self.big: set[str] = set()
        mock.route(url__regex=r"http://localhost:81\d\d/v1/internal/users/.*").mock(side_effect=self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        svc = PORT_TO_SVC[request.url.port]
        uid = request.url.path.split("/")[4]
        self.calls.append((request.method, svc, uid, dict(request.headers)))
        f = self.fail.get(svc)
        if isinstance(f, Exception):
            raise f
        if isinstance(f, int):
            return httpx.Response(f, json={"error": {"code": "x", "message": "x", "details": {}}})
        if request.method == "POST":
            data = {"blob": "x" * 5000} if svc in self.big else {"rows": [{"owner": uid}]}
            return httpx.Response(200, json={"service": svc, "user_id": uid, "truncated": False, "data": data})
        return httpx.Response(200, json={"service": svc, "user_id": uid, "status": "done", "counts": {}})

    def of(self, method, svc=None):
        return [c for c in self.calls if c[0] == method and (svc is None or c[1] == svc)]


@pytest.fixture
def fleet(mock_upstream):
    return Fleet(mock_upstream)


def register(c, email="a@example.com", name="Anas Secret"):
    t = c.post("/v1/auth/register", json={"email": email, "password": PW, "name": name}).json()
    return t, {"Authorization": f"Bearer {t['access_token']}"}


def delete(c, hdr, **body):
    return c.request("DELETE", "/v1/me", headers=hdr, json=body or {"password": PW})


def db(c, fn):
    async def run():
        async with c.app.state.sessionmaker() as s:
            return await fn(s)

    return c.portal.call(run)


# ------------------------------------------------------------------ export
def test_export_bundle_profile_and_all_services(client, fleet, auth, hdr):
    client.patch("/v1/me", headers=hdr, json={"company": "ACME"})
    r = client.get("/v1/me/export", headers=hdr)
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment")
    assert r.headers["cache-control"] == "no-store"
    b = json.loads(r.content)
    assert b["partial"] is False and b["user"]["id"] == auth["user"]["id"] and b["user"]["company"] == "ACME"
    assert set(b["services"]) == set(privacy.PRIVACY_SERVICES)
    assert all(v["status"] == "ok" for v in b["services"].values())
    assert b["services"]["rfq"]["data"]["rows"][0]["owner"] == auth["user"]["id"]
    assert "password" not in r.text and "hash" not in r.text
    assert all(c[2] == auth["user"]["id"] for c in fleet.calls)  # only the caller's id is ever sent


def test_export_forwards_internal_token_and_verified_supplier_only(make_client, mock_upstream):
    c = make_client(internal_token="int-secret", admin_token="adm")
    fleet = Fleet(mock_upstream)
    t, h = register(c)
    c.patch("/v1/me", headers=h, json={"supplier_id": "sup_a"})
    c.get("/v1/me/export", headers=h)
    assert all(x[3]["x-internal-token"] == "int-secret" for x in fleet.calls)
    assert "x-supplier-id" not in fleet.of("POST", "sourcing")[0][3]  # claim still pending: not forwarded
    c.post(f"/v1/admin/supplier-claims/{t['user']['id']}/approve", headers={"X-Admin-Token": "adm"})
    fleet.calls.clear()
    c.get("/v1/me/export", headers=h)
    assert fleet.of("POST", "sourcing")[0][3]["x-supplier-id"] == "sup_a"
    assert "x-supplier-id" not in fleet.of("POST", "rfq")[0][3]


def test_export_partial_failures_reported_per_service(client, fleet, hdr):
    fleet.fail.update(feed=503, media=httpx.ReadTimeout("slow"), rfq=httpx.ConnectError("down"))
    b = client.get("/v1/me/export", headers=hdr).json()
    assert b["partial"] is True
    assert b["services"]["feed"] == {"status": "error", "error": "http_503"}
    assert b["services"]["media"]["error"] == "unavailable" and b["services"]["rfq"]["error"] == "unavailable"
    assert b["services"]["messaging"]["status"] == "ok"


def test_export_size_cap(make_client, mock_upstream):
    c = make_client(export_max_bytes=3000)
    fleet = Fleet(mock_upstream)
    fleet.big = {"feed"}
    _, h = register(c)
    b = c.get("/v1/me/export", headers=h).json()
    assert b["services"]["feed"] == {"status": "error", "error": "too_large"}
    assert b["services"]["rfq"]["status"] == "ok" and b["partial"] is True


def test_export_requires_auth_and_is_rate_limited(client, fleet, hdr):
    assert client.get("/v1/me/export").status_code == 401
    codes = [client.get("/v1/me/export", headers=hdr).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


# ------------------------------------------------------------------ deletion
def test_delete_requires_reauth(client, fleet, hdr):
    assert client.request("DELETE", "/v1/me", headers=hdr, json={}).status_code == 422
    assert client.request("DELETE", "/v1/me", headers=hdr).status_code == 422
    r = delete(client, hdr, password="wrong-password")
    assert r.status_code == 403 and r.json()["error"]["code"] == "reauth_failed"
    assert client.request("DELETE", "/v1/me", json={"password": PW}).status_code == 401
    assert client.get("/v1/me", headers=hdr).status_code == 200 and not fleet.calls


def test_delete_anonymizes_and_fans_out(client, fleet, auth, hdr, capsys):
    uid = auth["user"]["id"]
    client.patch("/v1/me", headers=hdr, json={"phone": "+964 750 111 2222", "company": "ACME"})
    r = delete(client, hdr)
    assert r.status_code == 200
    out = r.json()
    assert out["status"] == "deleted" and set(out["services"]) == set(privacy.PRIVACY_SERVICES)
    assert set(out["services"].values()) == {"done"} and out["deleted_at"]
    assert {c[1] for c in fleet.of("DELETE")} == set(privacy.PRIVACY_SERVICES) and all(c[2] == uid for c in fleet.calls)

    u = db(client, lambda s: s.get(User, uid))
    assert (u.email, u.phone, u.company, u.supplier_id, u.default_destination) == (None, None, None, None, None)
    assert u.name == "Deleted user" and u.is_active is False and u.deleted_at is not None and u.id == uid
    assert db(client, lambda s: s.scalar(select(func.count()).select_from(RefreshToken))) == 0
    # sessions and credentials are dead
    assert client.post("/v1/auth/login", json={"email": "a@example.com", "password": PW}).status_code == 401
    assert client.post("/v1/auth/refresh", json={"refresh_token": auth["refresh_token"]}).status_code == 401
    assert client.get("/v1/me", headers=hdr).status_code == 403
    assert client.get("/v1/me/export", headers=hdr).status_code == 403
    # the email can be registered again by anyone: it is really free
    assert client.post("/v1/auth/register", json={"email": "a@example.com", "password": PW, "name": "New"}).status_code == 201
    # audit: durable events + log lines carry no PII
    events = db(client, lambda s: s.scalars(select(AccountEvent.event).where(AccountEvent.user_id == uid)))
    assert {"deletion_requested", "deletion_finalized"} <= set(events.all())
    logs = capsys.readouterr().out
    assert "deletion_requested" in logs and "a@example.com" not in logs and "Anas Secret" not in logs and "750" not in logs


def test_delete_with_refresh_token_proof(client, fleet, auth, hdr):
    r = client.request("DELETE", "/v1/me", headers=hdr, json={"refresh_token": auth["refresh_token"]})
    assert r.status_code == 200 and r.json()["status"] == "deleted"


def test_refresh_proof_of_another_user_is_rejected(client, fleet, auth, hdr):
    other, ohdr = register(client, "b@example.com", "B")
    r = client.request("DELETE", "/v1/me", headers=hdr, json={"refresh_token": other["refresh_token"]})
    assert r.status_code == 403 and r.json()["error"]["code"] == "reauth_failed"
    r = delete(client, ohdr, password="not-the-others-password")
    assert r.status_code == 403
    assert client.get("/v1/me", headers=hdr).status_code == 200 and client.get("/v1/me", headers=ohdr).status_code == 200
    assert not fleet.calls


def test_delete_only_touches_the_caller(client, fleet, auth, hdr):
    other, ohdr = register(client, "b@example.com", "B")
    assert delete(client, hdr).status_code == 200
    assert client.get("/v1/me", headers=ohdr).json()["email"] == "b@example.com"
    assert {c[2] for c in fleet.calls} == {auth["user"]["id"]}
    assert client.post("/v1/auth/login", json={"email": "b@example.com", "password": PW}).status_code == 200


def test_partial_failure_is_retried_by_the_durable_job_list(client, fleet, clock, auth, hdr):
    fleet.fail.update(feed=503, media=httpx.ConnectError("down"))
    r = delete(client, hdr)
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "partial" and body["services"]["feed"] == "pending" and body["services"]["rfq"] == "done"
    jobs = db(client, lambda s: s.scalars(select(DeletionJob).where(DeletionJob.status == "pending"))).all()
    assert {j.service for j in jobs} == {"feed", "media"} and all(j.attempts == 1 and j.last_error for j in jobs)
    n_before = len(fleet.calls)
    assert client.portal.call(privacy.run_jobs, client.app) == 0  # backoff: nothing is due yet
    assert len(fleet.calls) == n_before
    fleet.fail.clear()
    clock.advance(61)
    assert client.portal.call(privacy.process_due, client.app)["jobs"] == 2
    assert {c[1] for c in fleet.calls[n_before:]} == {"feed", "media"}
    again = delete(client, hdr)  # idempotent repeat: reports status, does not re-call finished services
    assert again.status_code == 200 and again.json()["status"] == "deleted"
    assert len(fleet.of("DELETE", "rfq")) == 1


def test_repeat_delete_retries_pending_immediately_and_is_idempotent(client, fleet, clock, hdr):
    fleet.fail["feed"] = 500
    assert delete(client, hdr).status_code == 202
    fleet.fail.clear()
    clock.advance(61)
    r = delete(client, hdr)
    assert r.status_code == 200 and r.json()["services"]["feed"] == "done"


def test_jobs_go_dead_after_max_attempts_and_show_in_admin(make_client, mock_upstream, clock):
    c = make_client(deletion_max_attempts=2, admin_token="adm")
    fleet = Fleet(mock_upstream)
    fleet.fail["trust"] = 500
    _, h = register(c)
    assert delete(c, h).json()["services"]["trust"] == "pending"
    clock.advance(61)
    c.portal.call(privacy.run_jobs, c.app)
    r = delete(c, h)
    assert r.status_code == 202 and r.json()["services"]["trust"] == "failed"
    items = c.get("/v1/admin/account-deletions", params={"status": "dead"}, headers={"X-Admin-Token": "adm"}).json()["items"]
    assert [(i["service"], i["last_error"]) for i in items] == [("trust", "http_500")]
    assert c.get("/v1/admin/account-deletions", headers={"X-Admin-Token": "bad"}).status_code == 401


def test_grace_period_schedules_and_login_cancels(make_client, mock_upstream, clock):
    c = make_client(deletion_grace_days=7)
    fleet = Fleet(mock_upstream)
    t, h = register(c)
    r = delete(c, h)
    assert r.status_code == 202 and r.json()["status"] == "scheduled" and r.json()["scheduled_for"] and not fleet.calls
    assert c.get("/v1/me", headers=h).status_code == 403  # soft-deleted: no access
    assert c.request("DELETE", "/v1/me", headers=h, json={"password": PW}).json()["status"] == "scheduled"  # idempotent
    assert c.post("/v1/auth/login", json={"email": "a@example.com", "password": "wrong-password"}).status_code == 401
    assert c.post("/v1/auth/login", json={"email": "a@example.com", "password": PW}).status_code == 200  # cancels
    assert db(c, lambda s: s.get(User, t["user"]["id"])).deletion_scheduled_at is None
    assert delete(c, {"Authorization": "Bearer " + c.post("/v1/auth/login", json={"email": "a@example.com", "password": PW}).json()["access_token"]}).status_code == 202
    clock.advance(6 * 86400)
    assert c.portal.call(privacy.process_due, c.app)["finalized"] == 0
    assert c.post("/v1/auth/login", json={"email": "a@example.com", "password": PW}).status_code == 200  # still cancellable
    h2 = {"Authorization": "Bearer " + c.post("/v1/auth/login", json={"email": "a@example.com", "password": PW}).json()["access_token"]}
    assert delete(c, h2).status_code == 202
    clock.advance(8 * 86400)
    assert c.portal.call(privacy.process_due, c.app)["finalized"] == 1
    assert len(fleet.of("DELETE")) == len(privacy.PRIVACY_SERVICES)
    assert c.post("/v1/auth/login", json={"email": "a@example.com", "password": PW}).status_code == 401


def test_admin_disabled_user_cannot_use_login_to_undelete(client, fleet, hdr):
    delete(client, hdr)
    assert client.post("/v1/auth/login", json={"email": "a@example.com", "password": PW}).status_code == 401


def test_internal_endpoints_are_not_reachable_through_the_gateway(client, fleet, hdr):
    for method in ("POST", "DELETE"):
        suffix = "export" if method == "POST" else "data"
        r = client.request(method, f"/v1/internal/users/usr_x/{suffix}", headers=hdr)
        assert r.status_code == 404
    assert not fleet.calls
