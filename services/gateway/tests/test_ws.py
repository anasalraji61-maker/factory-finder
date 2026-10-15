import pytest
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import InvalidStatus


@pytest.fixture(autouse=True)
def _legacy_token_fallback(monkeypatch):
    """The ?token= / Bearer handshake is off by default; most tests here exercise the legacy path."""
    monkeypatch.setenv("FF_GATEWAY_WS_ALLOW_TOKEN_PARAM", "true")


class FakeUp:
    def __init__(self, url, headers, behaviour):
        self.url, self.headers, self.sent, self.close_code = url, headers, [], None
        self.behaviour, self._q = behaviour, None

    async def __aenter__(self):
        import asyncio

        self._q = asyncio.Queue()
        await self._q.put("hello")
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, m):
        self.sent.append(m)
        if m == "bye":
            self.close_code = 4403
            await self._q.put(None)
        else:
            await self._q.put("echo:" + m)

    def __aiter__(self):
        return self

    async def __anext__(self):
        m = await self._q.get()
        if m is None:
            raise StopAsyncIteration
        return m

    async def close(self):
        pass


@pytest.fixture
def fake(client):
    box = {}

    def connect(url, additional_headers=None, **kw):
        if box.get("fail"):
            raise box["fail"]
        box["up"] = FakeUp(url, additional_headers, None)
        return box["up"]

    client.app.state.ws_connect = connect
    return box


def _code(client, url, **kw):
    with client.websocket_connect(url, **kw) as w:
        with pytest.raises(WebSocketDisconnect) as e:
            w.receive_text()
        return e.value.code


def test_no_token_4401(client, fake):
    assert _code(client, "/v1/ws/conversations/c1") == 4401
    assert "up" not in fake


def test_bad_token_4401(client, fake):
    assert _code(client, "/v1/ws/conversations/c1?token=garbage") == 4401


def test_unknown_path_rejected(client, fake, auth):
    assert (
        _code(client, "/v1/ws/other/x", headers={"Authorization": f"Bearer {auth['access_token']}"})
        == 4404
    )


def _finish(w):
    """End a session server-side ("bye" makes the fake upstream close) and wait for the
    gateway's close frame, so the app has finished before the TestClient cancels it.
    Leaving the block while the app is still closing races with the harness's cancel."""
    w.send_text("bye")
    with pytest.raises(WebSocketDisconnect) as e:
        while True:
            w.receive_text()
    return e.value.code


@pytest.mark.parametrize("via", ["header", "query"])
def test_pipe_and_identity(make_client, via):
    c = make_client(internal_token="int-secret")
    tok = c.post(
        "/v1/auth/register", json={"email": "w@example.com", "password": "password123", "name": "W"}
    ).json()
    box = {}

    def connect(url, additional_headers=None, **kw):
        box["up"] = FakeUp(url, additional_headers, None)
        return box["up"]

    c.app.state.ws_connect = connect
    a = tok["access_token"]
    kw = (
        {
            "headers": {
                "Authorization": f"Bearer {a}",
                "X-User-Id": "usr_evil",
                "X-Supplier-Id": "sup_evil",
            }
        }
        if via == "header"
        else {}
    )
    url = "/v1/ws/conversations/c1" + (f"?token={a}&user_id=usr_evil" if via == "query" else "")
    with c.websocket_connect(url, **kw) as w:
        assert w.receive_text() == "hello"
        w.send_text('{"type":"ping"}')
        assert w.receive_text() == 'echo:{"type":"ping"}'
        _finish(w)
    up = box["up"]
    assert up.url == "ws://localhost:8106/v1/ws/conversations/c1"  # no token / user_id forwarded
    assert (
        up.headers["X-User-Id"] == tok["user"]["id"]
        and up.headers["X-Internal-Token"] == "int-secret"
    )
    assert "X-Supplier-Id" not in up.headers
    assert up.sent == ['{"type":"ping"}', "bye"]


def test_upstream_close_code_propagated(client, fake, hdr):
    with client.websocket_connect("/v1/ws/conversations/c1", headers=hdr) as w:
        assert w.receive_text() == "hello"
        w.send_text("bye")
        with pytest.raises(WebSocketDisconnect) as e:
            w.receive_text()
        assert e.value.code == 4403


def test_upstream_handshake_403_maps_4403(client, fake, hdr):
    class R:
        status_code = 403

    err = InvalidStatus.__new__(InvalidStatus)
    err.response = R()
    fake["fail"] = err
    assert _code(client, "/v1/ws/conversations/c1", headers=hdr) == 4403


def test_upstream_down_1011(client, fake, hdr):
    fake["fail"] = ConnectionRefusedError()
    assert _code(client, "/v1/ws/conversations/c1", headers=hdr) == 1011


def test_ticket_requires_auth(client):
    assert client.post("/v1/ws-ticket").status_code == 401


def test_ticket_single_use_and_identity(client, fake, auth, hdr):
    r = client.post("/v1/ws-ticket", headers=hdr)
    assert r.status_code == 200
    body = r.json()
    assert body["expires_in"] == 30 and body["ticket"]
    url = f"/v1/ws/conversations/c1?ticket={body['ticket']}"
    with client.websocket_connect(url) as w:
        assert w.receive_text() == "hello"
        _finish(w)
    assert fake["up"].headers["X-User-Id"] == auth["user"]["id"]
    assert "ticket" not in fake["up"].url
    assert _code(client, url) == 4401  # burned


def test_ticket_expires(client, fake, hdr, clock):
    t = client.post("/v1/ws-ticket", headers=hdr).json()["ticket"]
    clock.advance(31)
    assert _code(client, f"/v1/ws/conversations/c1?ticket={t}") == 4401


def test_unknown_ticket_4401(client, fake):
    assert _code(client, "/v1/ws/conversations/c1?ticket=wst_nope") == 4401


def test_ticket_store_cap(clock):
    from ff_gateway.domain.ws_tickets import WsTicketStore

    st = WsTicketStore(clock, 30, 2)
    a, _ = st.issue_sync("u1")
    b, _ = st.issue_sync("u2")
    c, _ = st.issue_sync("u3")
    assert st.consume_sync(a) is None and st.consume_sync(b) == "u2" and st.consume_sync(c) == "u3"


def test_token_param_can_be_disabled(make_client):
    c = make_client(ws_allow_token_param=False)
    tok = c.post(
        "/v1/auth/register", json={"email": "z@example.com", "password": "password123", "name": "Z"}
    ).json()
    c.app.state.ws_connect = lambda *a, **k: None
    assert _code(c, f"/v1/ws/conversations/c1?token={tok['access_token']}") == 4401


def test_token_param_off_by_default(monkeypatch):
    from ff_gateway.config import Settings

    monkeypatch.delenv("FF_GATEWAY_WS_ALLOW_TOKEN_PARAM", raising=False)
    assert Settings(_env_file=None).ws_allow_token_param is False


def test_default_off_refuses_token_but_ticket_works(make_client, monkeypatch):
    monkeypatch.delenv("FF_GATEWAY_WS_ALLOW_TOKEN_PARAM", raising=False)
    c = make_client()
    tok = c.post("/v1/auth/register", json={"email": "d@example.com", "password": "password123", "name": "D"}).json()
    hdr = {"Authorization": f"Bearer {tok['access_token']}"}
    c.app.state.ws_connect = lambda url, additional_headers=None, **kw: FakeUp(url, additional_headers, None)
    assert _code(c, "/v1/ws/conversations/c1", headers=hdr) == 4401
    assert _code(c, f"/v1/ws/conversations/c1?token={tok['access_token']}") == 4401
    t = c.post("/v1/ws-ticket", headers=hdr).json()["ticket"]
    with c.websocket_connect(f"/v1/ws/conversations/c1?ticket={t}") as w:
        assert w.receive_text() == "hello"
        _finish(w)


def _ticket_url(c, hdr):
    t = c.post("/v1/ws-ticket", headers=hdr).json()["ticket"]
    return f"/v1/ws/conversations/c1?ticket={t}"


def test_per_user_connection_cap(make_client):
    c = make_client(ws_max_connections_per_user=2)
    tok = c.post("/v1/auth/register", json={"email": "cap@example.com", "password": "password123", "name": "C"}).json()
    hdr = {"Authorization": f"Bearer {tok['access_token']}"}
    c.app.state.ws_connect = lambda url, additional_headers=None, **kw: FakeUp(url, additional_headers, None)
    with c.websocket_connect(_ticket_url(c, hdr)) as w1, c.websocket_connect(_ticket_url(c, hdr)) as w2:
        assert w1.receive_text() == "hello" and w2.receive_text() == "hello"
        assert c.app.state.ws_local_counter.counts[tok["user"]["id"]] == 2
        assert _code(c, _ticket_url(c, hdr)) == 4429  # third socket refused
        _finish(w1)
        _finish(w2)
    assert c.app.state.ws_local_counter.counts == {}  # counters released
    with c.websocket_connect(_ticket_url(c, hdr)) as w:  # slot free again
        assert w.receive_text() == "hello"
        _finish(w)


def test_cap_is_per_user_and_releases_on_upstream_failure(make_client):
    c = make_client(ws_max_connections_per_user=1)
    tok = c.post("/v1/auth/register", json={"email": "cp@example.com", "password": "password123", "name": "C"}).json()
    hdr = {"Authorization": f"Bearer {tok['access_token']}"}

    def boom(*a, **k):
        raise ConnectionRefusedError()

    c.app.state.ws_connect = boom
    for _ in range(3):  # failed connects must not leak slots
        assert _code(c, _ticket_url(c, hdr)) == 1011
    assert c.app.state.ws_local_counter.counts == {}


def test_cap_off_with_zero(make_client):
    c = make_client(ws_max_connections_per_user=0)
    tok = c.post("/v1/auth/register", json={"email": "c0@example.com", "password": "password123", "name": "C"}).json()
    hdr = {"Authorization": f"Bearer {tok['access_token']}"}
    c.app.state.ws_connect = lambda url, additional_headers=None, **kw: FakeUp(url, additional_headers, None)
    ws = [c.websocket_connect(_ticket_url(c, hdr)) for _ in range(3)]
    opened = [w.__enter__() for w in ws]
    assert all(w.receive_text() == "hello" for w in opened)
    for w in reversed(opened):
        _finish(w)
        w.__exit__(None, None, None)


def test_handshake_uses_http_rate_limiter(make_client):
    c = make_client(rate_limit_per_minute=1000)
    c.app.state.settings.rate_limit_per_minute = 3
    c.app.state.ws_connect = lambda *a, **k: None
    codes = [_code(c, "/v1/ws/conversations/c1?ticket=wst_x") for _ in range(5)]
    assert codes[0] == 4401 and 4429 in codes[2:]


def test_ticket_issuance_rate_limited(make_client):
    c = make_client(ws_ticket_rate_limit_per_minute=2)
    tok = c.post("/v1/auth/register", json={"email": "tr@example.com", "password": "password123", "name": "T"}).json()
    hdr = {"Authorization": f"Bearer {tok['access_token']}"}
    assert [c.post("/v1/ws-ticket", headers=hdr).status_code for _ in range(3)] == [200, 200, 429]


def test_oversized_client_frame_not_relayed(client, fake, hdr):
    with client.websocket_connect("/v1/ws/conversations/c1", headers=hdr) as w:
        assert w.receive_text() == "hello"
        w.send_text("x" * (64 * 1024 + 1))
        with pytest.raises(WebSocketDisconnect) as e:
            while True:
                w.receive_text()
        assert e.value.code == 1009
    assert all(len(m) <= 64 * 1024 for m in fake["up"].sent)


def test_session_lifetime_closes_socket(make_client):
    c = make_client(ws_max_session_seconds=1)
    tok = c.post(
        "/v1/auth/register", json={"email": "life@example.com", "password": "password123", "name": "L"}
    ).json()
    box = {}

    def connect(url, additional_headers=None, **kw):
        box["up"] = FakeUp(url, additional_headers, None)
        return box["up"]

    c.app.state.ws_connect = connect
    h = {"Authorization": f"Bearer {tok['access_token']}"}
    with c.websocket_connect("/v1/ws/conversations/c1", headers=h) as w:
        assert w.receive_text() == "hello"
        with pytest.raises(WebSocketDisconnect) as e:
            while True:
                w.receive_text()
        assert e.value.code == 1001
