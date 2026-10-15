"""QA5: exotic-but-valid formats (CMYK/progressive JPEG, 16-bit/palette PNG, MPO, ICC) and metadata."""

import io

import pytest
from conftest import ALICE, upload
from PIL import Image


def _save(im, fmt, **kw):
    out = io.BytesIO()
    im.save(out, fmt, **kw)
    return out.getvalue()


def _gps_exif() -> bytes:
    ex = Image.Exif()
    ex[0x010F] = "SecretCam"
    ex.get_ifd(0x8825)[1] = "N"
    ex.get_ifd(0x8825)[2] = (31.0, 57.0, 0.0)
    return ex.tobytes()


CASES = {
    "cmyk_jpeg": lambda: _save(Image.new("CMYK", (40, 30), (10, 20, 30, 40)), "JPEG"),
    "progressive_jpeg_gps": lambda: _save(Image.new("RGB", (40, 30), "red"), "JPEG", progressive=True, exif=_gps_exif()),
    "palette_png_trans": lambda: _save(Image.new("P", (40, 30), 3), "PNG", transparency=0),
    "png_16bit": lambda: _save(Image.new("I;16", (40, 30), 1000), "PNG"),
    "png_icc": lambda: _save(Image.new("RGB", (40, 30), "blue"), "PNG", icc_profile=b"ICC" * 100),
    "webp_exif_icc": lambda: _save(Image.new("RGB", (40, 30), "green"), "WEBP", exif=_gps_exif(), icc_profile=b"ICC" * 50),
}


@pytest.mark.parametrize("name", CASES)
def test_exotic_valid_formats_accepted_and_clean(client, name):
    r = upload(client, CASES[name](), headers=ALICE)
    assert r.status_code in (200, 201), r.text
    body = client.get(r.json()["url"]).content
    assert b"SecretCam" not in body and b"GPS" not in body and b"ICC" * 3 not in body
    im = Image.open(io.BytesIO(body))
    assert not im.getexif() and "icc_profile" not in im.info
