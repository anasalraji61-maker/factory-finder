from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from pathlib import Path

from ff_media.storage.base import valid_key


class LocalDiskStorage:
    """Files under ``root/<first 2 chars of key>/<key>``. Keys are regex-validated and the resolved
    path must stay inside the resolved root (no traversal, no symlink escape)."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()  # created lazily on first write (no import-time side effects)

    def path_for(self, key: str) -> Path:
        if not valid_key(key):
            raise ValueError("invalid storage key")
        p = (self.root / key[:2] / key).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("path escapes the storage root")
        return p

    def _put(self, key: str, data: bytes) -> None:
        p = self.path_for(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, p)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def _get(self, key: str) -> bytes | None:
        try:
            p = self.path_for(key)
        except ValueError:
            return None
        try:
            return p.read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            return None

    def _delete(self, key: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path_for(key).unlink()

    def _list_keys(self) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []
        if not self.root.is_dir():
            return out
        for sub in self.root.iterdir():
            if not sub.is_dir() or sub.is_symlink():
                continue
            for f in sub.iterdir():
                if f.is_file() and not f.is_symlink() and valid_key(f.name):
                    out.append((f.name, f.stat().st_mtime))
        return out

    async def list_keys(self) -> list[tuple[str, float]]:
        """(key, mtime) of every stored blob; temp files and foreign names are ignored."""
        return await asyncio.to_thread(self._list_keys)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(self._put, key, data)

    async def get(self, key: str) -> bytes | None:
        return await asyncio.to_thread(self._get, key)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._delete, key)

    async def exists(self, key: str) -> bool:
        try:
            return await asyncio.to_thread(self.path_for(key).is_file)
        except ValueError:
            return False

    async def ping(self) -> bool:
        def probe() -> bool:
            self.root.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".ready-")
            os.close(fd)
            os.unlink(tmp)
            return True

        try:
            return await asyncio.to_thread(probe)
        except OSError:
            return False
