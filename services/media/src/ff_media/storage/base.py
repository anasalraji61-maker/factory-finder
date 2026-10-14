"""Storage abstraction. Keys are produced only by ``make_key`` and validated by ``valid_key``."""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

ID_RE = re.compile(r"[a-f0-9]{32}")  # always used with fullmatch (``$`` would accept a trailing newline)
EXTS = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
WIDTHS = (200, 400, 800)
FILENAME_RE = re.compile(r"([a-f0-9]{32})\.(jpg|png|webp)")
KEY_RE = re.compile(r"(p-)?[a-f0-9]{32}(_w(200|400|800))?\.(jpg|png|webp)")


def make_key(media_id: str, ext: str, width: int | None = None, private: bool = False) -> str:
    """Private files live under a distinct ``p-`` key so the public route can never address them."""
    key = f"{media_id}.{ext}" if width is None else f"{media_id}_w{width}.{ext}"
    if private:
        key = "p-" + key
    if not KEY_RE.fullmatch(key):
        raise ValueError("invalid storage key")
    return key


def valid_key(key: str) -> bool:
    return bool(KEY_RE.fullmatch(key))


@runtime_checkable
class StorageBackend(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def get(self, key: str) -> bytes | None: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    async def ping(self) -> bool:
        """True when the backend is usable (never raises)."""
        ...
