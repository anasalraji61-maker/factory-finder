import io
import struct
import zlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ff_media.config import Settings
from ff_media.main import create_app

ALICE = {"X-User-Id": "alice"}
BOB = {"X-User-Id": "bob"}


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


def make_settings(tmp_path, **over) -> Settings:
    base = {"database_url": "sqlite+aiosqlite:///:memory:", "storage_root": str(tmp_path / "store"),
            "public_base_url": "https://api.example.test"}
    return Settings(**{**base, **over})


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def make_client(tmp_path, clock):
    opened = []

    def _make(**over):
        s = make_settings(tmp_path, **over)
        c = TestClient(create_app(s, clock=clock))
        c.__enter__()
        c.settings, c.root = s, tmp_path / "store"
        opened.append(c)
        return c

    yield _make
    for c in opened:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


def img_bytes(fmt="PNG", size=(64, 48), color=(200, 30, 30), **save) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, fmt, **save)
    return out.getvalue()


def noise_png(size=(900, 600), seed=1) -> bytes:
    """Distinct content per seed so dedupe does not kick in."""
    import random

    rnd = random.Random(seed)
    im = Image.new("RGB", size)
    im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(size[0] * size[1])])
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def solid(seed: int, size=(32, 32)) -> bytes:
    return img_bytes("PNG", size, (seed % 256, (seed // 256) % 256, 7))


def upload(client, data: bytes, *, headers=ALICE, filename="p.png", ctype="image/png", kind=None, name="file"):
    kw = {"data": {"kind": kind}} if kind else {}
    return client.post("/v1/media/images", files={name: (filename, data, ctype)}, headers=headers, **kw)


def png_header(width: int, height: int) -> bytes:
    """A syntactically valid PNG whose IHDR claims huge dimensions (tiny on the wire)."""

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00" * 16)) + chunk(b"IEND", b"")
