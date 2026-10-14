import json

from conftest import uh


def _lines(capsys):
    return [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]


def test_health_and_ready(client):
    assert client.get("/health").json() == {"status": "ok", "service": "feed", "version": "0.1.0"}
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready" and r.json()["service"] == "feed"


def test_ready_503_when_database_down(client, monkeypatch):
    async def down(_engine):
        return False

    monkeypatch.setattr("ff_feed.main.db_ready", down)
    assert client.get("/ready").status_code == 503


def test_request_id_and_log_line(client, capsys):
    r = client.get("/v1/feed/trending?cursor=secret-ish", headers={**uh("u7"), "X-Request-Id": "req-123"})
    assert r.headers["x-request-id"] == "req-123"
    line = [x for x in _lines(capsys) if x["path"] == "/v1/feed/trending"][-1]
    assert line["service"] == "feed" and line["user_id"] == "u7" and line["status"] in (200, 422)
    assert "secret-ish" not in json.dumps(line)


def test_route_template_logged_not_raw_id(client, capsys):
    client.get("/v1/feed/posts/post_abc123", headers=uh())
    assert any(x["path"] == "/v1/feed/posts/{post_id}" for x in _lines(capsys))
