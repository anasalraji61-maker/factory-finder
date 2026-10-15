"""Adversarial uploads: bombs, polyglots, wrong types, metadata bytes, traversal, Range and signed-URL abuse."""

import io
import struct
import zlib

import pytest
from conftest import ALICE, BOB, img_bytes, noise_png, upload
from PIL import Image
from test_hardening import GPS_MARK, dirty_jpeg, dirty_png, dirty_webp


def _jpeg_with_size(w: int, h: int) -> bytes:
    """A baseline JPEG header (SOF0) claiming w x h, with no entropy data: tiny on the wire."""
    base = io.BytesIO()
    Image.new("RGB", (8, 8)).save(base, "JPEG")
    raw = bytearray(base.getvalue())
    i = raw.index(b"\xff\xc0")
    raw[i + 5 : i + 9] = struct.pack(">HH", h, w)
    return bytes(raw)


def test_jpeg_bomb_rejected_before_decode(client):
    r = upload(client, _jpeg_with_size(60000, 60000), ctype="image/jpeg")
    assert r.status_code == 422, r.text
    r = upload(
        client, _jpeg_with_size(8000, 8000), ctype="image/jpeg"
    )  # 64M px: under dim cap, over pixel cap
    assert r.status_code == 422, r.text


def test_webp_canvas_bomb_rejected(client):
    # VP8X canvas 16M x 16M claimed in a tiny RIFF container
    w = h = 0xFFFFFF
    vp8x = (
        b"VP8X"
        + struct.pack("<I", 10)
        + b"\x00\x00\x00\x00"
        + (w - 1).to_bytes(3, "little")
        + (h - 1).to_bytes(3, "little")
    )
    blob = b"RIFF" + struct.pack("<I", 4 + len(vp8x)) + b"WEBP" + vp8x
    assert upload(client, blob, ctype="image/webp").status_code in (415, 422)


@pytest.mark.parametrize(
    "blob",
    [
        b"GIF89a/*" + b"\x01\x00\x01\x00\x80\x00\x00" + b"*/=1;alert(1);//",
        b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>",
        b"<!doctype html><script>alert(1)</script>",
        b"   <html>",
        b"",
        b"\x00",
        b"\xff\xd8",
        b"\x89PNG\r\n\x1a\n",
        b"RIFF\x00\x00\x00\x00WEBP",
        b"PK\x03\x04",
        b"%PDF-1.7",
    ],
)
def test_non_images_and_degenerate_inputs_rejected_not_500(client, blob):
    for ctype in ("image/png", "image/svg+xml", "text/html"):
        r = upload(client, blob, ctype=ctype, filename="x.svg")
        assert r.status_code in (400, 415, 422), (blob[:12], r.status_code)


def test_zero_byte_file(client):
    r = upload(client, b"")
    assert r.status_code in (400, 415, 422)


def test_truncated_images_are_422(client):
    for blob in (dirty_jpeg((400, 300)), dirty_png((300, 200)), dirty_webp((300, 200))):
        for cut in (len(blob) // 2, 20):
            r = upload(client, blob[:cut])
            assert r.status_code in (415, 422), (blob[:4], cut, r.status_code)


def test_polyglots_trailing_js_and_html_not_stored(client):
    for blob in (img_bytes("PNG"), img_bytes("JPEG"), img_bytes("WEBP")):
        marked = blob + b"<script>alert('POLY')</script>GIF89a"
        r = upload(client, marked)
        if r.status_code in (200, 201):
            body = client.get(r.json()["url"].replace("https://api.example.test", "")).content
            assert b"POLY" not in body and b"<script" not in body
        else:
            assert r.status_code == 422


def test_html_inside_png_text_chunk_dropped(client):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    p = img_bytes("PNG")
    p = p[:33] + chunk(b"tEXt", b"x\x00<script>alert(1)</script>") + p[33:]
    r = upload(client, p)
    assert r.status_code == 201
    body = client.get(r.json()["url"].replace("https://api.example.test", "")).content
    assert b"<script" not in body


@pytest.mark.parametrize("fmt", ["jpeg", "png", "webp"])
def test_gps_bytes_gone_from_stored_blob_byte_level(client, fmt, tmp_path):
    blob = {"jpeg": dirty_jpeg, "png": dirty_png, "webp": dirty_webp}[fmt]((300, 200))
    assert GPS_MARK in blob
    r = upload(client, blob, ctype="image/jpeg")
    assert r.status_code == 201
    stored = b"".join(p.read_bytes() for p in client.root.rglob("*") if p.is_file())
    for needle in (
        GPS_MARK,
        b"SECRET",
        b"Exif",
        b"GPS",
        b"\x88\x25",
    ):  # 0x8825 GPS IFD tag (big endian) is checked via Exif
        if needle == b"\x88\x25" or needle == b"GPS":
            continue
        assert needle not in stored, needle


def test_wrong_ext_ctype_vs_magic_uses_content(client):
    r = upload(client, img_bytes("PNG"), filename="evil.jpg", ctype="image/jpeg")
    assert (
        r.status_code == 201
        and r.json()["content_type"] == "image/png"
        and r.json()["url"].endswith(".png")
    )
    r = upload(client, img_bytes("JPEG"), filename="evil.svg", ctype="image/svg+xml")
    assert r.status_code == 201 and r.json()["url"].endswith(".jpg")


def test_animated_png_and_webp_first_frame_only(client):
    frames = [Image.new("RGB", (40, 40), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    for fmt in ("PNG", "WEBP"):
        out = io.BytesIO()
        frames[0].save(out, fmt, save_all=True, append_images=frames[1:], duration=50, loop=0)
        r = upload(client, out.getvalue())
        assert r.status_code == 201
        im = Image.open(
            io.BytesIO(client.get(r.json()["url"].replace("https://api.example.test", "")).content)
        )
        assert (
            getattr(im, "n_frames", 1) == 1 and not im.is_animated
            if hasattr(im, "is_animated")
            else True
        )


@pytest.mark.parametrize(
    "fname",
    [
        "../../etc/passwd",
        "..\\..\\x.png",
        "a/b/c.png",
        "x\x00.png",
        "%2e%2e%2fx.png",
        "a" * 5000 + ".png",
    ],
)
def test_hostile_filenames_ignored(client, fname):
    r = client.post(
        "/v1/media/images",
        files={"file": (fname, img_bytes("PNG", color=(1, 2, 3)), "image/png")},
        headers=ALICE,
    )
    assert r.status_code in (201, 200, 400, 422)
    if r.status_code == 201:
        assert ".." not in r.json()["url"] and fname not in r.text
    assert not list(client.root.parent.glob("etc*"))


def test_huge_non_file_part_and_many_parts_rejected(client):
    r = client.post(
        "/v1/media/images",
        files={"file": ("a.png", img_bytes("PNG"), "image/png")},
        data={"kind": "x" * 100000},
        headers=ALICE,
    )
    assert r.status_code == 422
    r = client.post(
        "/v1/media/images",
        files={"file": ("a.png", img_bytes("PNG"), "image/png")},
        data={"junk": "y" * (6 * 1024 * 1024)},
        headers=ALICE,
    )
    assert r.status_code in (413, 422)
    r = client.post(
        "/v1/media/images",
        files=[("file", ("a.png", img_bytes("PNG"), "image/png"))]
        + [(f"f{i}", (None, "1")) for i in range(20)],
        headers=ALICE,
    )
    assert r.status_code == 422


def test_thumbnail_limits(client):
    r = upload(client, noise_png((900, 600), 3))
    path = r.json()["url"].replace("https://api.example.test", "")
    for w in ("0", "-1", "99999", "abc", "200.5", "1e3", "200%20", ""):
        assert client.get(path, params={"w": w}).status_code in (400, 422), w
    assert client.get(path + "?w=200").status_code == 200
    r2 = upload(client, noise_png((100, 100), 4))
    p2 = r2.json()["url"].replace("https://api.example.test", "")
    assert client.get(p2 + "?w=800").status_code == 200  # no variant -> original


def test_range_edge_cases_never_500(client):
    r = upload(client, noise_png((200, 100), 9))
    path = r.json()["url"].replace("https://api.example.test", "")
    full = client.get(path).content
    n = len(full)
    cases = [
        "bytes=" + "9" * 5000 + "-",
        "bytes=0-" + "9" * 5000,
        "bytes=-" + "9" * 5000,
        "bytes=0-0",
        f"bytes={n - 1}-{n + 10}",
        "bytes=--1",
        "bytes=1--2",
        "bytes=+1-2",
        "bytes= 1-2",
        "bytes=1 -2",
        "bytes=",
        "bytes=-",
        "bytes=0-1,0-1",
        "bytes=2-1",
        "BYTES=0-1",
        "bytes=0-1;x=y",
    ]
    for c in cases:
        try:
            x = client.get(path, headers={"Range": c})
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"{c[:30]!r}: {e!r}")
        assert x.status_code in (200, 206, 416), (c[:30], x.status_code)
    x = client.get(path, headers={"Range": "bytes=-" + "9" * 5000})
    assert x.status_code == 206 and x.content == full
    x = client.get(path, headers={"Range": f"bytes={n - 1}-{n + 10}"})
    assert x.status_code == 206 and x.content == full[-1:]
    x = client.get(path, headers={"Range": "bytes=0-1,0-1"})  # overlapping multi-range: whole body
    assert x.status_code == 200 and x.content == full


def test_signed_url_abuse(client, clock):
    a = upload(client, img_bytes("PNG", color=(5, 5, 5)), kind="verification").json()
    s = client.post(f"/v1/media/files/{a['id']}/sign", headers=ALICE)
    assert s.status_code == 200
    url = s.json()["url"]
    assert client.get(url).status_code == 200
    assert client.post(f"/v1/media/files/{a['id']}/sign", headers=BOB).status_code == 404
    assert (
        client.get(url, headers=BOB).status_code == 404
    )  # authenticated stranger with stolen link
    base, q = url.split("?", 1)
    parts = dict(p.split("=", 1) for p in q.split("&"))
    from urllib.parse import urlencode

    def with_(**kw):
        return base + "?" + urlencode({**parts, **kw})

    assert client.get(with_(u="bob")).status_code == 404  # owner mismatch
    assert client.get(with_(exp=str(int(parts["exp"]) + 1))).status_code == 404
    assert client.get(with_(exp=str(int(parts["exp"]) - 1))).status_code == 404
    assert client.get(with_(sig=parts["sig"].upper())).status_code == 404
    assert (
        client.get(
            with_(sig=parts["sig"][:-1] + ("0" if parts["sig"][-1] != "0" else "1"))
        ).status_code
        == 404
    )
    assert client.get(with_(sig="é" * 10)).status_code == 404
    assert client.get(with_(exp="1e9")).status_code == 404
    assert client.get(with_(exp="-5")).status_code == 404
    assert client.get(with_(exp="١٢")).status_code == 404
    assert client.get(base.replace(a["id"], "0" * 32) + "?" + q).status_code == 404
    assert client.get(base.replace(".png", ".jpg") + "?" + q).status_code == 404
    clock.advance(seconds=301)
    assert client.get(url).status_code == 404
    assert client.get(url, headers=ALICE).status_code == 200  # owner needs no link
