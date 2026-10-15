"""Image validation and re-encoding (CPU bound: call from a thread).

The format is decided ONLY by magic bytes. Pixels are decoded and re-encoded into a fresh image, so no metadata
(EXIF, GPS, ICC, XMP, PNG text chunks) survives. EXIF orientation is applied before it is dropped.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field

from PIL import Image, ImageOps, UnidentifiedImageError

from ff_media.errors import DimensionsExceeded, InvalidImage, UnsupportedMediaType
from ff_media.storage.base import WIDTHS

Image.MAX_IMAGE_PIXELS = 64_000_000  # Pillow's own bomb guard; our configured limits are stricter

FORMATS = {"jpeg": ("JPEG", "jpg", "image/jpeg"), "png": ("PNG", "png", "image/png"), "webp": ("WEBP", "webp", "image/webp")}


def sniff(data: bytes) -> str | None:
    """'jpeg' | 'png' | 'webp' from the leading bytes, else None."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@dataclass
class Processed:
    content_type: str
    ext: str
    width: int
    height: int
    data: bytes
    sha256: str
    variants: dict[int, bytes] = field(default_factory=dict)


def _encode(im: Image.Image, fmt: str, quality: int) -> bytes:
    out = io.BytesIO()
    if fmt == "JPEG":
        im.save(out, "JPEG", quality=quality, optimize=True)
    elif fmt == "PNG":
        im.save(out, "PNG", optimize=True)
    else:
        im.save(out, "WEBP", quality=quality, method=4)
    return out.getvalue()


def _clean(im: Image.Image, fmt: str) -> Image.Image:
    """A fresh image holding only pixels (no info dict, no exif, no profile)."""
    has_alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    if fmt == "JPEG":
        target = "L" if im.mode == "L" else "RGB"
    else:
        target = "RGBA" if has_alpha else ("L" if im.mode in ("L", "1") else "RGB")
    if im.mode != target:
        im = im.convert(target)
    return Image.frombytes(im.mode, im.size, im.tobytes())


def process_image(data: bytes, *, max_dimension: int, max_pixels: int, jpeg_quality: int = 85) -> Processed:
    kind = sniff(data)
    if kind is None:
        raise UnsupportedMediaType("Only JPEG, PNG and WebP images are accepted")
    fmt, ext, content_type = FORMATS[kind]
    try:
        im = Image.open(io.BytesIO(data), formats=[fmt])  # lazy: reads the header only
        if im.format != fmt:
            raise UnsupportedMediaType("Only JPEG, PNG and WebP images are accepted")
        w, h = im.size
        if w < 1 or h < 1 or w > max_dimension or h > max_dimension or w * h > max_pixels:
            raise DimensionsExceeded(
                f"Image is {w}x{h}; limit is {max_dimension}x{max_dimension} and {max_pixels} pixels",
                {"width": w, "height": h, "max_dimension": max_dimension, "max_pixels": max_pixels},
            )
        im.seek(0)  # animated PNG/WebP: first frame only
        im.load()
        im = ImageOps.exif_transpose(im)  # JPEG/WebP/PNG(eXIf) orientation
    except (UnsupportedMediaType, DimensionsExceeded):
        raise
    except Image.DecompressionBombError as e:
        raise DimensionsExceeded("Image has too many pixels") from e
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombWarning) as e:
        raise InvalidImage("The file is not a valid image") from e
    try:
        clean = _clean(im, fmt)
        body = _encode(clean, fmt, jpeg_quality)
        variants: dict[int, bytes] = {}
        for width in WIDTHS:
            if width < clean.width:
                small = clean.resize((width, max(1, round(clean.height * width / clean.width))), Image.LANCZOS)
                variants[width] = _encode(small, fmt, jpeg_quality)
    except (OSError, ValueError) as e:
        raise InvalidImage("The image could not be processed") from e
    return Processed(content_type, ext, clean.width, clean.height, body, hashlib.sha256(body).hexdigest(), variants)
