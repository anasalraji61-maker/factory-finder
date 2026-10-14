import io
import re

import pytest
from conftest import ALICE, BOB, img_bytes, noise_png, png_header, solid, upload
from PIL import Image

ID_URL = re.compile(r"^https://api\.example\.test/v1/media/files/([a-f0-9]{32})\.(jpg|png|webp)$")


def path_of(url: str) -> str:
    return url.removeprefix("https://api.example.test")


@pytest.mark.parametrize(("fmt", "ext", "ctype"), [("PNG", "png", "image/png"), ("JPEG", "jpg", "image/jpeg"), ("WEBP", "webp", "image/webp")])
def test_upload_and_fetch(client, fmt, ext, ctype):
    r = upload(client, img_bytes(fmt, (120, 80)), filename="whatever.bin", ctype="application/octet-stream")
    assert r.status_code == 201, r.text
    b = r.json()
    m = ID_URL.match(b["url"])
    assert m and m.group(1) == b["id"] and m.group(2) == ext
    assert (b["width"], b["height"], b["content_type"], b["kind"]) == (120, 80, ctype, "listing")
    assert len(b["sha256"]) == 64 and b["bytes"] > 0 and b["widths"] == []
    g = client.get(path_of(b["url"]))  # public: no headers at all
    assert g.status_code == 200 and g.headers["content-type"] == ctype and len(g.content) == b["bytes"]
    assert Image.open(io.BytesIO(g.content)).size == (120, 80)


def test_relative_url_without_public_base(make_client):
    c = make_client(public_base_url=None)
    assert upload(c, solid(1)).json()["url"].startswith("/v1/media/files/")


def test_kind_validation(client):
    assert upload(client, solid(1), kind="avatar").json()["kind"] == "avatar"
    r = upload(client, solid(2), kind="evil")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_requires_user(client):
    r = client.post("/v1/media/images", files={"file": ("a.png", solid(1), "image/png")})
    assert r.status_code == 401 and r.json()["error"]["code"] == "missing_user"
    assert client.delete("/v1/media/images/" + "a" * 32).status_code == 401


def test_missing_or_double_file(client):
    assert upload(client, solid(1), name="other").status_code == 422
    r = client.post("/v1/media/images", files=[("file", ("a.png", solid(1), "image/png")), ("file", ("b.png", solid(2), "image/png"))], headers=ALICE)
    assert r.status_code == 422
    assert client.post("/v1/media/images", json={"a": 1}, headers=ALICE).status_code == 415


# ------------------------------------------------------------------ magic bytes
def test_png_bytes_named_jpg_is_treated_as_png(client):
    r = upload(client, img_bytes("PNG"), filename="x.jpg", ctype="image/jpeg")
    assert r.status_code == 201 and r.json()["content_type"] == "image/png" and r.json()["url"].endswith(".png")


@pytest.mark.parametrize(
    "payload",
    [
        b"<html><script>alert(1)</script></html>",
        b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
        b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
        b"GIF89a\x01\x00\x01\x00\x00\x00\x00;",
        b"%PDF-1.4 fake",
        b"MZ\x90\x00 executable",
        b"",
        b"\x89PNG",  # too short but starts like png
    ],
)
def test_non_images_rejected_whatever_the_client_claims(client, payload):
    for ctype, name in (("image/png", "a.png"), ("image/jpeg", "a.jpg"), ("image/svg+xml", "a.svg")):
        r = upload(client, payload, filename=name, ctype=ctype)
        assert r.status_code in (415, 422), (payload, r.status_code)
        assert r.json()["error"]["code"] in ("unsupported_media_type", "invalid_image")
    assert upload(client, b"<html>x</html>", filename="a.png").json()["error"]["code"] == "unsupported_media_type"


def test_png_magic_with_garbage_body_is_invalid_image(client):
    r = upload(client, b"\x89PNG\r\n\x1a\n" + b"garbage" * 50)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_image"


def test_polyglot_html_after_jpeg_header_is_destroyed_by_reencode(client):
    jpg = img_bytes("JPEG")
    r = upload(client, jpg + b"<html><script>alert(1)</script></html>", filename="a.jpg", ctype="image/jpeg")
    assert r.status_code == 201
    body = client.get(path_of(r.json()["url"])).content
    assert b"<script" not in body and body[:3] == b"\xff\xd8\xff"


# ------------------------------------------------------------------ size / bombs
def test_oversize_rejected_413(make_client):
    c = make_client(max_upload_bytes=50_000)
    big = noise_png((300, 300))  # > 50 KB
    assert len(big) > 50_000
    r = upload(c, big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
    assert not list(c.root.rglob("*.png"))


def test_oversize_enforced_while_streaming_without_content_length(make_client):
    c = make_client(max_upload_bytes=10_000)
    boundary = "XXBOUNDARYXX"
    head = f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.png"\r\nContent-Type: image/png\r\n\r\n'.encode()
    tail = f"\r\n--{boundary}--\r\n".encode()

    def gen():  # chunked: no Content-Length, 5 MB of body
        yield head
        for _ in range(80):
            yield b"\x89PNG\r\n\x1a\n" + b"A" * 65_000
        yield tail

    r = c.post("/v1/media/images", content=gen(), headers={**ALICE, "content-type": f"multipart/form-data; boundary={boundary}"})
    assert r.status_code == 413


def test_default_limit_is_5mb(client):
    assert client.settings.max_upload_bytes == 5 * 1024 * 1024


def test_declared_dimensions_bomb_rejected_before_decoding(client):
    r = upload(client, png_header(30_000, 30_000))  # claims 900 MP, ~100 bytes on the wire
    assert r.status_code == 422 and r.json()["error"]["code"] == "image_dimensions_exceeded"


def test_dimension_limits(make_client):
    c = make_client(max_dimension=100, max_pixels=5_000)
    assert upload(c, img_bytes("PNG", (101, 10))).json()["error"]["code"] == "image_dimensions_exceeded"
    assert upload(c, img_bytes("PNG", (90, 90))).json()["error"]["code"] == "image_dimensions_exceeded"  # 8100 px
    assert upload(c, img_bytes("PNG", (70, 70))).status_code == 201


def test_default_dimension_limit_8000(client):
    assert upload(client, png_header(8001, 10)).status_code == 422
    assert upload(client, png_header(8000, 8000)).status_code == 422  # 64 MP > pixel cap


# ------------------------------------------------------------------ metadata stripping
def _jpeg_with_gps(orientation: int | None = None) -> bytes:
    im = Image.new("RGB", (100, 50), (10, 120, 200))
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"
    if orientation:
        exif[0x0112] = orientation
    exif.get_ifd(0x8825).update({1: "N", 2: (33.0, 18.0, 0.0), 3: "E", 4: (44.0, 24.0, 0.0)})
    out = io.BytesIO()
    im.save(out, "JPEG", exif=exif.tobytes())
    data = out.getvalue()
    assert Image.open(io.BytesIO(data)).getexif().get_ifd(0x8825)  # sanity: the GPS IFD is really embedded
    return data


def test_exif_gps_removed_from_jpeg(client):
    r = upload(client, _jpeg_with_gps(), filename="p.jpg", ctype="image/jpeg")
    assert r.status_code == 201
    for url in (path_of(r.json()["url"]),):
        body = client.get(url).content
        assert not Image.open(io.BytesIO(body)).getexif()
        assert b"Exif" not in body and b"SecretCameraMaker" not in body and b"GPS" not in body


def test_exif_orientation_applied_then_stripped(client):
    r = upload(client, _jpeg_with_gps(orientation=6), filename="p.jpg", ctype="image/jpeg")  # rotate 90 cw
    b = r.json()
    assert (b["width"], b["height"]) == (50, 100)
    assert not Image.open(io.BytesIO(client.get(path_of(b["url"])).content)).getexif()


def test_png_text_chunks_and_webp_exif_removed(client):
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("Author", "SecretAuthor")
    out = io.BytesIO()
    Image.new("RGB", (20, 20), (1, 2, 3)).save(out, "PNG", pnginfo=info)
    assert b"SecretAuthor" in out.getvalue()
    r = upload(client, out.getvalue())
    assert b"SecretAuthor" not in client.get(path_of(r.json()["url"])).content

    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"
    exif.get_ifd(0x8825).update({1: "N", 2: (1.0, 2.0, 3.0)})
    out = io.BytesIO()
    Image.new("RGB", (20, 20), (9, 9, 9)).save(out, "WEBP", exif=exif.tobytes())
    r = upload(client, out.getvalue(), filename="p.webp", ctype="image/webp")
    body = client.get(path_of(r.json()["url"])).content
    assert r.status_code == 201 and b"SecretCameraMaker" not in body and b"EXIF" not in body


def test_png_transparency_preserved(client):
    out = io.BytesIO()
    Image.new("RGBA", (10, 10), (255, 0, 0, 0)).save(out, "PNG")
    body = client.get(path_of(upload(client, out.getvalue()).json()["url"])).content
    assert Image.open(io.BytesIO(body)).convert("RGBA").getpixel((0, 0))[3] == 0


# ------------------------------------------------------------------ thumbnails
def test_thumbnail_sizes(client):
    b = upload(client, noise_png((1000, 500))).json()
    assert b["widths"] == [200, 400, 800]
    url = path_of(b["url"])
    for w in (200, 400, 800):
        g = client.get(url, params={"w": w})
        assert g.status_code == 200
        assert Image.open(io.BytesIO(g.content)).size == (w, w // 2)
    assert Image.open(io.BytesIO(client.get(url).content)).size == (1000, 500)


def test_thumbnail_not_upscaled(client):
    b = upload(client, noise_png((300, 300), seed=5)).json()
    assert b["widths"] == [200]
    assert Image.open(io.BytesIO(client.get(path_of(b["url"]), params={"w": 800}).content)).size == (300, 300)


@pytest.mark.parametrize("w", ["100", "199", "1200", "0", "-5", "abc", "800.5"])
def test_only_allowed_widths(client, w):
    b = upload(client, solid(3)).json()
    r = client.get(path_of(b["url"]), params={"w": w})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


# ------------------------------------------------------------------ dedupe & quotas
def test_dedupe_per_owner(client):
    data = noise_png((64, 64), seed=3)
    a = upload(client, data)
    b = upload(client, data, filename="other.png")
    assert a.status_code == 201 and b.status_code == 200 and a.json()["id"] == b.json()["id"]
    c = upload(client, data, headers=BOB)  # another owner gets their own copy
    assert c.status_code == 201 and c.json()["id"] != a.json()["id"] and c.json()["sha256"] == a.json()["sha256"]
    assert len(list(client.root.rglob("*.png"))) == 2


def test_file_quota(make_client):
    c = make_client(max_files_per_user=3)
    for i in range(3):
        assert upload(c, solid(i)).status_code == 201
    r = upload(c, solid(99))
    assert r.status_code == 429 and r.json()["error"]["code"] == "quota_files_exceeded"
    assert upload(c, solid(0)).status_code == 200  # dedupe is not a new file
    assert upload(c, solid(99), headers=BOB).status_code == 201  # per user
    first = upload(c, solid(0)).json()["id"]
    assert c.delete(f"/v1/media/images/{first}", headers=ALICE).status_code == 204
    assert upload(c, solid(99)).status_code == 201  # space freed


def test_hourly_quota_rolls(make_client, clock):
    c = make_client(max_uploads_per_hour=3)
    for i in range(3):
        assert upload(c, solid(i)).status_code == 201
    r = upload(c, solid(50))
    assert r.status_code == 429 and r.json()["error"]["code"] == "quota_uploads_exceeded"
    assert 1 <= int(r.headers["retry-after"]) <= 3601
    assert upload(c, solid(50), headers=BOB).status_code == 201
    clock.advance(minutes=61)
    assert upload(c, solid(50)).status_code == 201


def test_invalid_uploads_count_towards_hourly_quota(make_client):
    c = make_client(max_uploads_per_hour=2)
    assert upload(c, b"<html>").status_code == 415
    assert upload(c, b"<html>").status_code == 415
    assert upload(c, solid(1)).status_code == 429


# ------------------------------------------------------------------ ownership
def test_delete_owner_only_and_idor(client):
    b = upload(client, solid(1)).json()
    url = path_of(b["url"])
    for hdrs in (BOB, {"X-User-Id": "alice2"}):
        r = client.delete(f"/v1/media/images/{b['id']}", headers=hdrs)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert client.get(url).status_code == 200  # still there
    assert client.delete(f"/v1/media/images/{'0' * 32}", headers=BOB).json() == client.delete(f"/v1/media/images/{b['id']}", headers=BOB).json()
    assert client.delete(f"/v1/media/images/{b['id']}", headers=ALICE).status_code == 204
    assert client.get(url).status_code == 404
    assert client.delete(f"/v1/media/images/{b['id']}", headers=ALICE).status_code == 404
    assert not [p for p in client.root.rglob("*") if p.is_file()]


def test_delete_removes_variants(client):
    b = upload(client, noise_png((1000, 400), seed=9)).json()
    assert len([p for p in client.root.rglob("*.png")]) == 4
    client.delete(f"/v1/media/images/{b['id']}", headers=ALICE)
    assert not list(client.root.rglob("*.png"))
    assert client.get(path_of(b["url"]), params={"w": 200}).status_code == 404


# ------------------------------------------------------------------ serving / traversal / headers
def test_serving_headers(client):
    b = upload(client, solid(1), filename="a.png").json()
    g = client.get(path_of(b["url"]))
    assert g.headers["x-content-type-options"] == "nosniff"
    assert g.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert g.headers["content-type"] == "image/png"
    assert "default-src 'none'" in g.headers["content-security-policy"]
    assert g.headers["content-disposition"].startswith("inline")
    r304 = client.get(path_of(b["url"]), headers={"If-None-Match": g.headers["etag"]})
    assert r304.status_code == 304 and r304.headers["x-content-type-options"] == "nosniff"


def test_wrong_extension_is_404(client):
    b = upload(client, solid(1)).json()
    for ext in ("jpg", "webp"):
        assert client.get(f"/v1/media/files/{b['id']}.{ext}").status_code == 404


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/passwd", "..%2f..%2fetc%2fpasswd", "%2e%2e/%2e%2e/etc/passwd", "....//....//etc/passwd",
        "/etc/passwd", "..\\..\\windows\\win.ini", "a" * 32 + ".png/../../x", "A" * 32 + ".png",
        "g" * 32 + ".png", "a" * 31 + ".png", "a" * 33 + ".png", "a" * 32 + ".svg", "a" * 32 + ".png%00.jpg",
        "a" * 32 + ".PNG", "a" * 32, ".png", "a" * 32 + "_w200.png", "%00", "a" * 32 + ".png%0a",
    ],
)
def test_traversal_and_malformed_names_are_404(client, name):
    upload(client, solid(1))
    r = client.get(f"/v1/media/files/{name}")
    assert r.status_code in (404, 405) and "root:" not in r.text
    assert client.delete(f"/v1/media/images/{name}", headers=ALICE).status_code in (404, 405)


def test_storage_refuses_bad_keys_and_escapes(tmp_path):
    from ff_media.storage import LocalDiskStorage

    (tmp_path / "root").mkdir()
    st = LocalDiskStorage(tmp_path / "root")
    for key in ("../x.png", "/etc/passwd", "a/b.png", "a" * 32 + ".png/../x", "x" * 32 + ".png"):
        with pytest.raises(ValueError):
            st.path_for(key)
    (tmp_path / "outside").mkdir()
    (tmp_path / "root" / "aa").symlink_to(tmp_path / "outside")  # symlink escape attempt
    with pytest.raises(ValueError):
        st.path_for("aa" + "b" * 30 + ".png")


def test_ids_are_random_and_long(client):
    ids = {upload(client, solid(i)).json()["id"] for i in range(5)}
    assert len(ids) == 5 and all(re.fullmatch(r"[a-f0-9]{32}", i) for i in ids)
