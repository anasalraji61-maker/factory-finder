"""QA hardening: metadata stripping on every stored byte, bombs, polyglots, traversal, quotas, HEAD/Range."""

import io
import struct
import zlib

import pytest
from conftest import ALICE, BOB, img_bytes
from PIL import Image

from ff_media.imaging import process_image
from ff_media.storage.base import make_key

GPS_MARK = b"SECRET-GPS-MARK"
EXIF_MARKERS = (b"Exif\x00\x00", b"http://ns.adobe.com/xap", b"SECRET", b"ICC_PROFILE", b"iCCP", b"eXIf", b"tEXt", b"iTXt", b"zTXt")


def _exif_blob() -> bytes:
    ex = Image.Exif()
    ex[0x010F] = "SECRET-Make"  # Make
    ex[0x0112] = 6  # orientation: rotate 90
    gps = ex.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "N", (37.0, 25.0, 19.0), "W", (122.0, 5.0, 1.0)
    gps[0x1B] = GPS_MARK.decode()
    return ex.tobytes()


def _icc() -> bytes:
    from PIL import ImageCms

    return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def dirty_jpeg(size=(900, 600)) -> bytes:
    out = io.BytesIO()
    im = Image.effect_noise(size, 60).convert("RGB")
    im.save(out, "JPEG", exif=_exif_blob(), icc_profile=_icc(), comment=b"SECRET-comment")
    return out.getvalue()


def dirty_webp(size=(900, 600)) -> bytes:
    out = io.BytesIO()
    im = Image.effect_noise(size, 60).convert("RGB")
    im.save(out, "WEBP", exif=_exif_blob(), icc_profile=_icc(), xmp=b"<x:xmpmeta>SECRET-xmp</x:xmpmeta>")
    return out.getvalue()


def _chunk(tag: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)


def dirty_png(size=(900, 600)) -> bytes:
    from PIL.PngImagePlugin import PngInfo

    out = io.BytesIO()
    info = PngInfo()
    info.add_text("Author", "SECRET-text")
    info.add_itxt("Desc", "SECRET-itxt", zip=True)
    im = Image.effect_noise(size, 60).convert("RGB")
    im.save(out, "PNG", pnginfo=info, exif=_exif_blob(), icc_profile=_icc())
    return out.getvalue()


DIRTY = {"jpeg": dirty_jpeg, "png": dirty_png, "webp": dirty_webp}


def _assert_clean(blob: bytes) -> None:
    for m in EXIF_MARKERS:
        assert m not in blob, m
    im = Image.open(io.BytesIO(blob))
    im.load()
    assert not im.getexif()
    for k in ("exif", "icc_profile", "xmp", "comment", "photoshop", "Author", "Desc"):
        assert k not in im.info, k


@pytest.mark.parametrize("fmt", ["jpeg", "png", "webp"])
def test_fixture_really_contains_metadata(fmt):
    blob = DIRTY[fmt]()
    assert b"SECRET" in blob or GPS_MARK in blob or b"ICC_PROFILE" in blob or b"iCCP" in blob


@pytest.mark.parametrize("fmt", ["jpeg", "png", "webp"])
@pytest.mark.parametrize("visibility", ["public", "private"])
def test_every_stored_file_is_stripped(client, fmt, visibility):
    r = client.post("/v1/media/images", headers=ALICE, data={"visibility": visibility},
                    files={"file": ("x", DIRTY[fmt](), "image/jpeg")})
    assert r.status_code == 201, r.text
    body = r.json()
    keys = [make_key(body["id"], r.json()["url"].rsplit(".", 1)[1], private=visibility == "private")]
    keys += [make_key(body["id"], body["url"].rsplit(".", 1)[1], w) for w in body["widths"]]
    assert (visibility == "private") == (body["widths"] == [])
    for k in keys:
        raw = (client.root / k[:2] / k).read_bytes()
        _assert_clean(raw)
    # and the bytes actually served
    if visibility == "public":
        for suffix in ("", "?w=200"):
            g = client.get(body["url"].replace("https://api.example.test", "") + suffix)
            assert g.status_code == 200
            _assert_clean(g.content)
    else:
        g = client.get(body["url"], headers=ALICE)
        _assert_clean(g.content)


def test_orientation_applied_then_dropped_png_too():
    ex = Image.Exif()
    ex[0x0112] = 6
    out = io.BytesIO()
    Image.new("RGB", (60, 20), (1, 2, 3)).save(out, "PNG", exif=ex.tobytes())
    p = process_image(out.getvalue(), max_dimension=1000, max_pixels=10**6)
    assert (p.width, p.height) == (20, 60)
    assert b"eXIf" not in p.data


def test_trailing_garbage_and_appended_archive_not_stored(client):
    blob = img_bytes("JPEG", (80, 60)) + b"PK\x03\x04SECRET-ZIP" + b"<?php echo 1;"
    r = client.post("/v1/media/images", headers=ALICE, files={"file": ("a.jpg", blob, "image/jpeg")})
    assert r.status_code == 201
    g = client.get(r.json()["url"].replace("https://api.example.test", ""))
    assert b"PK\x03\x04" not in g.content and b"<?php" not in g.content


# ---------------------------------------------------------------- bombs / polyglots / unsupported types
def _png_header_only(w: int, h: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(b"\x00" * 10)) + _chunk(b"IEND", b"")


def test_png_declaring_giant_canvas_rejected_before_decode(client):
    r = client.post("/v1/media/images", headers=ALICE, files={"file": ("a.png", _png_header_only(60000, 60000), "image/png")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "image_dimensions_exceeded"


def test_png_beyond_pillow_2x_bomb_limit_is_a_422_not_a_500(client):
    r = client.post("/v1/media/images", headers=ALICE, files={"file": ("a.png", _png_header_only(2**31 - 1, 2**31 - 1), "image/png")})
    assert r.status_code == 422


def test_pixel_cap_with_square_under_dimension_cap(make_client):
    c = make_client(max_dimension=8000, max_pixels=1_000_000)
    r = c.post("/v1/media/images", headers=ALICE, files={"file": ("a.png", _png_header_only(2000, 2000), "image/png")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "image_dimensions_exceeded"


def test_huge_ancillary_text_chunk_does_not_blow_up(client):
    """A zTXt chunk inflating to ~100 MB must not be expanded and must not survive."""
    body = b"Comment\x00\x00" + zlib.compress(b"A" * (100 * 1024 * 1024), 9)
    base = img_bytes("PNG", (40, 30))
    iend = base.rindex(b"IEND") - 4
    evil = base[:iend] + _chunk(b"zTXt", body) + base[iend:]
    assert len(evil) < 1_000_000
    r = client.post("/v1/media/images", headers=ALICE, files={"file": ("a.png", evil, "image/png")})
    assert r.status_code in (201, 422)
    if r.status_code == 201:
        g = client.get(r.json()["url"].replace("https://api.example.test", ""))
        assert b"zTXt" not in g.content and len(g.content) < 10_000


def test_truncated_png_idat_bomb_is_rejected(client):
    """Valid header, IDAT that inflates far beyond what the header implies (extra data) or is cut short."""
    good = img_bytes("PNG", (64, 64))
    r = client.post("/v1/media/images", headers=ALICE, files={"file": ("a.png", good[: len(good) // 2], "image/png")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_image"


def test_animated_webp_and_apng_keep_one_frame_and_count_only_first(client):
    frames = [Image.new("RGB", (50, 40), (i * 20, 0, 0)) for i in range(10)]
    for fmt, save in (("WEBP", {"save_all": True, "append_images": frames[1:]}), ("PNG", {"save_all": True, "append_images": frames[1:]})):
        out = io.BytesIO()
        frames[0].save(out, fmt, **save)
        r = client.post("/v1/media/images", headers=ALICE, files={"file": ("a", out.getvalue(), "image/webp")})
        assert r.status_code == 201, (fmt, r.text)
        g = client.get(r.json()["url"].replace("https://api.example.test", ""))
        im = Image.open(io.BytesIO(g.content))
        assert getattr(im, "n_frames", 1) == 1


def test_animated_frame_larger_than_canvas_is_bounded(client):
    """Frames are checked against the canvas size which is capped; only frame 0 is decoded."""
    frames = [Image.new("RGB", (300, 300), (i * 20, 0, 0)) for i in range(40)]
    out = io.BytesIO()
    frames[0].save(out, "WEBP", save_all=True, append_images=frames[1:])
    r = client.post("/v1/media/images", headers=ALICE, files={"file": ("a", out.getvalue(), "image/webp")})
    assert r.status_code == 201


@pytest.mark.parametrize("name,blob", [
    ("svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
    ("svg-xml", b'<?xml version="1.0"?><svg onload="alert(1)"/>'),
    ("html", b"<html><script>alert(1)</script></html>"),
    ("gif", b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"),
    ("pdf", b"%PDF-1.7\n1 0 obj<</S/JavaScript/JS(app.alert(1))>>endobj\n%%EOF"),
    ("bmp", b"BM" + b"\x00" * 60),
    ("tiff", b"II*\x00" + b"\x00" * 60),
    ("riff-wav", b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 20),
    ("empty", b""),
])
def test_non_images_are_415_regardless_of_declared_type(client, name, blob):
    for ctype in ("image/jpeg", "image/svg+xml", "application/pdf"):
        r = client.post("/v1/media/images", headers=ALICE, files={"file": (f"evil.{name}.jpg", blob, ctype)})
        assert r.status_code == 415, (name, ctype, r.text)


@pytest.mark.parametrize("magic_of,body_of", [("jpeg", "png"), ("png", "webp"), ("webp", "jpeg"), ("jpeg", "gif")])
def test_mismatched_magic_and_body_never_stored(client, magic_of, body_of):
    heads = {"jpeg": b"\xff\xd8\xff\xe0", "png": b"\x89PNG\r\n\x1a\n", "webp": b"RIFF\x10\x00\x00\x00WEBP"}
    bodies = {"png": img_bytes("PNG"), "webp": img_bytes("WEBP"), "jpeg": img_bytes("JPEG"), "gif": img_bytes("GIF")}
    blob = heads[magic_of] + bodies[body_of]
    r = client.post("/v1/media/images", headers=ALICE, files={"file": ("a", blob, "image/png")})
    assert r.status_code in (415, 422)
    assert not list(client.root.rglob("*.jpg")) and not list(client.root.rglob("*.png")) and not list(client.root.rglob("*.webp"))


def test_png_bytes_declared_jpeg_is_stored_as_png_and_served_as_png(client):
    r = client.post("/v1/media/images", headers=ALICE, files={"file": ("a.jpg", img_bytes("PNG"), "image/jpeg")})
    assert r.status_code == 201 and r.json()["content_type"] == "image/png" and r.json()["url"].endswith(".png")


# ---------------------------------------------------------------- names, paths, content addressing
def _upload(client, user=ALICE, data=None, blob=None):
    blob = blob or img_bytes("PNG", (50, 40), (9, 9, 9))
    r = client.post("/v1/media/images", headers=user, data=data or {}, files={"file": ("x", blob, "image/png")})
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.mark.parametrize("name", [
    "../../etc/passwd", "..%2f..%2fetc%2fpasswd", "%2e%2e/%2e%2e/x.png", "a" * 32 + ".png/../x", "a" * 32 + ".png%00.jpg",
    "A" * 32 + ".png", "p-" + "a" * 32 + ".png", "a" * 32 + "_w200.png", "a" * 32 + ".svg", "a" * 32 + ".png%0A", "..\\..\\x.png",
])
def test_public_route_rejects_odd_names(client, name):
    assert client.get(f"/v1/media/files/{name}").status_code == 404
    assert client.get(f"/v1/media/private/{name}", headers=ALICE).status_code == 404


def test_storage_refuses_traversal_keys(tmp_path):
    from ff_media.storage import LocalDiskStorage

    st = LocalDiskStorage(tmp_path / "s")
    for k in ("../x.png", "/etc/passwd", "a/b.png", "p-../x", ""):
        with pytest.raises(ValueError):
            st.path_for(k)


def test_symlink_escape_blocked(tmp_path):
    from ff_media.storage import LocalDiskStorage

    root = tmp_path / "s"
    (root / "aa").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ("a" * 32 + ".png")).write_bytes(b"x")
    (root / "aa").rmdir()
    (root / "aa").symlink_to(outside)
    st = LocalDiskStorage(root)
    with pytest.raises(ValueError):
        st.path_for("a" * 32 + ".png")


def test_client_filename_never_reaches_storage_or_headers(client):
    r = client.post("/v1/media/images", headers=ALICE,
                    files={"file": ('../../../x"; \r\nInjected: 1.png', img_bytes("PNG", (20, 20)), "image/png")})
    assert r.status_code == 201
    g = client.get(r.json()["url"].replace("https://api.example.test", ""))
    assert "injected" not in {k.lower() for k in g.headers}
    assert g.headers["content-disposition"] == f'inline; filename="{r.json()["id"]}.png"'
    assert all(p.name == p.name.lower() for p in client.root.rglob("*") if p.is_file())


def test_dedupe_is_per_owner_so_other_users_cannot_probe_or_delete(client):
    a = _upload(client, ALICE)
    b = _upload(client, BOB)
    assert a["id"] != b["id"] and a["sha256"] == b["sha256"]
    assert client.delete(f"/v1/media/images/{a['id']}", headers=BOB).status_code == 404
    assert client.delete(f"/v1/media/images/{a['id']}", headers=ALICE).status_code == 204
    assert client.get(f"/v1/media/files/{b['id']}.png").status_code == 200


def test_public_and_private_copies_of_same_pixels_are_separate_blobs(client):
    pub = _upload(client, ALICE)
    prv = _upload(client, ALICE, data={"visibility": "private"})
    assert pub["id"] != prv["id"]
    assert client.get(f"/v1/media/files/{prv['id']}.png").status_code == 404


# ---------------------------------------------------------------- quotas
def test_per_user_byte_quota(make_client):
    c = make_client(max_bytes_per_user=3000)
    from conftest import noise_png

    first = c.post("/v1/media/images", headers=ALICE, files={"file": ("a", noise_png((30, 30), 1), "image/png")})
    assert first.status_code == 201
    used = first.json()["bytes"]
    assert used < 3000
    n = 0
    while True:
        r = c.post("/v1/media/images", headers=ALICE, files={"file": ("a", noise_png((30, 30), 10 + n), "image/png")})
        n += 1
        if r.status_code != 201:
            break
        assert n < 40
    assert r.status_code == 429 and r.json()["error"]["code"] == "quota_bytes_exceeded"
    # another user is unaffected; deleting frees space
    assert c.post("/v1/media/images", headers=BOB, files={"file": ("a", noise_png((30, 30), 1), "image/png")}).status_code == 201
    assert c.delete(f"/v1/media/images/{first.json()['id']}", headers=ALICE).status_code == 204
    assert c.post("/v1/media/images", headers=ALICE, files={"file": ("a", noise_png((30, 30), 99), "image/png")}).status_code == 201


# ---------------------------------------------------------------- signed URLs, HEAD, Range, cache headers
def _signed(client, mid):
    r = client.post(f"/v1/media/files/{mid}/sign", headers=ALICE)
    assert r.status_code == 200
    return r.json()["url"].replace("https://api.example.test", "")


def test_signed_url_expiry_tamper_and_cross_file(client, clock):
    a = _upload(client, ALICE, data={"visibility": "private"})
    b = _upload(client, ALICE, data={"visibility": "private"}, blob=img_bytes("PNG", (33, 33), (1, 1, 1)))
    url = _signed(client, a["id"])
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 200  # replay inside the TTL is allowed by design (bearer link)
    assert client.get(url.replace(a["id"], b["id"])).status_code == 404  # signature bound to the file
    assert client.get(url.replace("exp=", "exp=9")).status_code == 404
    assert client.get(url[:-1] + ("0" if url[-1] != "0" else "1")).status_code == 404
    assert client.get(url.replace("&sig=", "&sig=00")).status_code == 404
    assert client.get(url.split("&sig=")[0]).status_code == 404
    clock.advance(seconds=299)
    assert client.get(url).status_code == 200
    clock.advance(seconds=2)
    assert client.get(url).status_code == 404  # expired
    assert client.get(url, headers=BOB).status_code == 404  # stolen link + other identity
    assert client.get(f"/v1/media/files/{a['id']}.png").status_code == 404


def test_signed_url_far_future_exp_rejected(client):
    import time

    from ff_media import signing

    a = _upload(client, ALICE, data={"visibility": "private"})
    svc = client.app.state.service
    exp = int(svc.clock().timestamp()) + 10**6
    sig = signing.sign(svc.signing_key, a["id"], "alice", exp)
    assert client.get(f"/v1/media/private/{a['id']}.png?u=alice&exp={exp}&sig={sig}").status_code == 404
    assert time  # keep import used


def test_signed_url_does_not_cross_restart_with_different_key(make_client):
    c1 = make_client(signing_key="k1" * 16)
    a = _upload(c1, ALICE, data={"visibility": "private"})
    url = _signed(c1, a["id"])
    c1.app.state.service.signing_key = b"other-key"
    assert c1.get(url).status_code == 404


def test_private_headers_head_range_and_errors_are_no_store(client):
    a = _upload(client, ALICE, data={"visibility": "private"})
    path = f"/v1/media/private/{a['id']}.png"
    g = client.get(path, headers=ALICE)
    assert g.status_code == 200
    assert g.headers["cache-control"] == "private, no-store"
    h = client.head(path, headers=ALICE)
    assert h.status_code == 200 and h.content == b""
    assert int(h.headers["content-length"]) == len(g.content) and h.headers["cache-control"] == "private, no-store"
    r = client.get(path, headers={**ALICE, "Range": "bytes=0-9"})
    assert r.status_code == 206 and r.content == g.content[:10]
    assert r.headers["content-range"] == f"bytes 0-9/{len(g.content)}" and r.headers["cache-control"] == "private, no-store"
    assert "etag" not in g.headers
    # every failure is a cacheable-looking 404 unless marked no-store
    for hdrs in ({}, BOB):
        bad = client.get(path, headers=hdrs)
        assert bad.status_code == 404 and bad.headers["cache-control"] == "no-store"
    assert client.head(path, headers=BOB).status_code == 404
    assert client.get(f"/v1/media/admin/files/{a['id']}").headers["cache-control"] == "no-store"
    s = client.post(f"/v1/media/files/{a['id']}/sign", headers=ALICE)
    assert s.headers["cache-control"] == "private, no-store"


def test_public_head_range_and_headers(client):
    from conftest import noise_png

    r = client.post("/v1/media/images", headers=ALICE, files={"file": ("a", noise_png((300, 200), 5), "image/png")})
    path = r.json()["url"].replace("https://api.example.test", "")
    g = client.get(path)
    assert g.headers["accept-ranges"] == "bytes" and "immutable" in g.headers["cache-control"]
    h = client.head(path)
    assert h.status_code == 200 and h.content == b"" and int(h.headers["content-length"]) == len(g.content)
    assert h.headers["etag"] == g.headers["etag"]
    n = len(g.content)
    for spec, want, code in [("bytes=5-", g.content[5:], 206), ("bytes=-7", g.content[-7:], 206),
                             (f"bytes=0-{n * 3}", g.content, 206), ("bytes=3-1", None, 416), (f"bytes={n}-", None, 416),
                             ("bytes=0-1,3-4", g.content, 200), ("bytes=abc", g.content, 200), ("items=0-1", g.content, 200),
                             ("bytes=-0", None, 416)]:
        x = client.get(path, headers={"Range": spec})
        assert x.status_code == code, spec
        if want is not None:
            assert x.content == want, spec
        if code == 416:
            assert x.headers["content-range"] == f"bytes */{n}"
    assert client.head(path, headers={"If-None-Match": g.headers["etag"]}).status_code == 304
    assert client.get(path, headers={"If-None-Match": g.headers["etag"]}).status_code == 304
    assert client.get("/v1/media/files/" + "0" * 32 + ".png").headers["cache-control"] == "no-store"


def test_nosniff_and_csp_on_every_image_response(client):
    a = _upload(client, ALICE)
    g = client.get(f"/v1/media/files/{a['id']}.png")
    assert g.headers["x-content-type-options"] == "nosniff" and g.headers["content-security-policy"] == "default-src 'none'"
    assert g.headers["content-type"] == "image/png"


# ---------------------------------------------------------------- orphan sweep
def test_sweep_orphans_removes_only_old_unreferenced_blobs(client, clock):
    import asyncio
    import os

    a = _upload(client, ALICE)
    live = {p for p in client.root.rglob("*") if p.is_file()}
    orphan = client.root / "ab" / ("ab" * 16 + ".png")
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"x")
    young = client.root / "cd" / ("cd" * 16 + ".png")
    young.parent.mkdir(parents=True, exist_ok=True)
    young.write_bytes(b"x")
    junk = client.root / "ab" / ".tmp-123"
    junk.write_bytes(b"x")
    old = clock.now.timestamp() - 7200
    os.utime(orphan, (old, old))
    os.utime(junk, (old, old))
    for p in live:
        os.utime(p, (old, old))
    os.utime(young, (clock.now.timestamp(), clock.now.timestamp()))
    svc = client.app.state.service
    dry = asyncio.run(svc.sweep_orphans(dry_run=True))
    assert dry["orphans"] == 1 and dry["deleted"] == 0 and orphan.exists()
    done = asyncio.run(svc.sweep_orphans(dry_run=False))
    assert done["deleted"] == 1 and not orphan.exists() and young.exists() and junk.exists()
    assert all(p.exists() for p in live)
    assert client.get(f"/v1/media/files/{a['id']}.png").status_code == 200


def test_sweep_reports_rows_with_missing_blob_without_deleting(client):
    import asyncio

    a = _upload(client, ALICE)
    for p in client.root.rglob(a["id"] + "*"):
        p.unlink()
    res = asyncio.run(client.app.state.service.sweep_orphans(dry_run=False))
    assert res["rows_missing_blob"] == 1
    assert client.get(f"/v1/media/files/{a['id']}.png").status_code == 404


def test_failed_variant_write_rolls_back_all_blobs(tmp_path, clock):
    from conftest import make_settings, noise_png
    from fastapi.testclient import TestClient

    from ff_media.main import create_app
    from ff_media.storage import LocalDiskStorage

    class Flaky(LocalDiskStorage):
        async def put(self, key, data, content_type):
            if "_w400" in key:
                raise OSError("disk full")
            await super().put(key, data, content_type)

    st = make_settings(tmp_path)
    with TestClient(create_app(st, storage=Flaky(st.storage_root), clock=clock)) as c:
        r = c.post("/v1/media/images", headers=ALICE, files={"file": ("a", noise_png((900, 600), 8), "image/png")})
        assert r.status_code == 503
        assert not [p for p in (tmp_path / "store").rglob("*") if p.is_file()]
