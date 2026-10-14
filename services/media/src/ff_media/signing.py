"""Short-lived HMAC-signed URLs for private files.

Signature = HMAC-SHA256(key, "ffm1|private|<media_id>|<user_id>|<exp>") as lowercase hex; bound to the file id, the
user the link was issued to (the owner) and the expiry. Compared in constant time on bytes.
"""

from __future__ import annotations

import hashlib
import hmac


def _msg(media_id: str, user_id: str, exp: int) -> bytes:
    return f"ffm1|private|{media_id}|{user_id}|{exp}".encode()


def sign(key: bytes, media_id: str, user_id: str, exp: int) -> str:
    return hmac.new(key, _msg(media_id, user_id, exp), hashlib.sha256).hexdigest()


def verify(key: bytes, media_id: str, user_id: str, exp: int, sig: str) -> bool:
    expected = sign(key, media_id, user_id, exp)
    return hmac.compare_digest(sig.encode("utf-8", "replace"), expected.encode())
