import json
import logging

import pytest
from conftest import ALICE, make_settings, solid, upload
from fastapi.testclient import TestClient

from ff_media.main import create_app
from ff_media.storage import LocalDiskStorage, S3Storage, StorageBackend, build_storage


def test_health_ready(client):
    assert client.get("/health").json()["service"] == "media"
    assert client.get("/ready").json() == {"status": "ready", "service": "media", "checks": {"database": True, "storage": True}}


def test_ready_503_when_storage_down(tmp_path):
    class Dead(LocalDiskStorage):
        async def ping(self) -> bool:
            return False

    with TestClient(create_app(make_settings(tmp_path), storage=Dead(tmp_path / "s"))) as c:
        r = c.get("/ready")
        assert r.status_code == 503 and r.json()["checks"]["storage"] is False


def test_storage_failure_is_503_and_leaves_nothing(tmp_path):
    class Broken(LocalDiskStorage):
        async def put(self, key, data, content_type):
            raise OSError("disk full")

    with TestClient(create_app(make_settings(tmp_path), storage=Broken(tmp_path / "s"))) as c:
        r = upload(c, solid(1))
        assert r.status_code == 503 and r.json()["error"]["code"] == "storage_unavailable"
        assert upload(c, solid(1)).status_code == 503  # nothing recorded -> still retryable


def test_internal_token(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, internal_token="tok-xyz"))) as c:
        assert c.get("/health").status_code == 200
        assert upload(c, solid(1)).status_code == 401
        assert upload(c, solid(1), headers={**ALICE, "X-Internal-Token": "tok-xyz"}).status_code == 201


def test_logs_have_no_sensitive_data(client, caplog, capsys):
    with caplog.at_level(logging.INFO, logger="ff.request"):
        b = upload(client, solid(1), headers={**ALICE, "Authorization": "Bearer tok-123"}).json()
        client.get(f"/v1/media/files/{b['id']}.png?w=200&secret=qq")
    out = capsys.readouterr().out + caplog.text
    lines = [json.loads(x) for x in out.splitlines() if x.startswith("{")]
    assert lines and all(x["service"] == "media" for x in lines)
    assert {x["path"] for x in lines} >= {"/v1/media/images", "/v1/media/files/{filename}"}
    for needle in (b["id"], b["sha256"], "tok-123", "secret=qq"):
        assert needle not in out


def test_storage_backends(tmp_path):
    assert isinstance(LocalDiskStorage(tmp_path / "a"), StorageBackend)
    assert isinstance(build_storage(make_settings(tmp_path)), LocalDiskStorage)
    with pytest.raises(ValueError):
        build_storage(make_settings(tmp_path, storage_backend="ftp"))
    with pytest.raises(ValueError):  # s3 is off unless fully configured
        build_storage(make_settings(tmp_path, storage_backend="s3"))


class NoSuchKey(Exception):
    pass


class Exc:
    NoSuchKey = NoSuchKey


async def test_s3_skeleton_with_fake_client():
    store = {}

    class Fake:
        exceptions = Exc

        def put_object(self, Bucket, Key, Body, **kw):
            store[Key] = Body

        def get_object(self, Bucket, Key):
            if Key not in store:
                raise NoSuchKey()
            import io

            return {"Body": io.BytesIO(store[Key])}

        def delete_object(self, Bucket, Key):
            store.pop(Key, None)

        def head_object(self, Bucket, Key):
            if Key not in store:
                raise NoSuchKey()

        def head_bucket(self, Bucket):
            return {}

    s3 = S3Storage("b", client=Fake())
    key = "a" * 32 + ".png"
    await s3.put(key, b"x", "image/png")
    assert store == {"media/" + key: b"x"} and await s3.get(key) == b"x" and await s3.exists(key)
    await s3.delete(key)
    assert await s3.get(key) is None and await s3.ping()
    with pytest.raises(ValueError):
        await s3.put("../x.png", b"", "image/png")
