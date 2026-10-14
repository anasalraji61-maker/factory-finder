import pytest
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import InvalidStatus


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


def retry_on_cancel(times=3):
    """Starlette's TestClient can raise CancelledError when leaving a websocket
    block while the app is still closing (a test-harness race, not a gateway bug)."""
    import concurrent.futures
    import functools

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            for attempt in range(times):
                try:
                    return fn(*a, **kw)
                except concurrent.futures.CancelledError:
                    if attempt == times - 1:
                        raise

        return wrapper

    return deco


@pytest.mark.parametrize("via", ["header", "query"])
@retry_on_cancel()
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
    up = box["up"]
    assert up.url == "ws://localhost:8106/v1/ws/conversations/c1"  # no token / user_id forwarded
    assert (
        up.headers["X-User-Id"] == tok["user"]["id"]
        and up.headers["X-Internal-Token"] == "int-secret"
    )
    assert "X-Supplier-Id" not in up.headers
    assert up.sent == ['{"type":"ping"}']


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
