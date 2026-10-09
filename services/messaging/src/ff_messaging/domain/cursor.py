"""Opaque cursors for message pagination (newest first, ``before`` = older page)."""

import base64
import binascii

from ff_messaging.domain.errors import BadRequestError

_PREFIX = "s1:"
_MAX_CURSOR_LENGTH = 64


def encode_cursor(seq: int) -> str:
    raw = f"{_PREFIX}{seq}".encode("ascii")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(cursor: str) -> int:
    """Return the message sequence number encoded in ``cursor``.

    Raises ``BadRequestError(code="invalid_cursor")`` for anything that was not produced by
    :func:`encode_cursor`.
    """
    invalid = BadRequestError("Cursor is malformed or expired", code="invalid_cursor")
    if not cursor or len(cursor) > _MAX_CURSOR_LENGTH:
        raise invalid
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("ascii")
    except (binascii.Error, UnicodeError, ValueError) as exc:
        raise invalid from exc
    if not raw.startswith(_PREFIX):
        raise invalid
    digits = raw[len(_PREFIX) :]
    if not digits.isdigit() or not digits.isascii():
        raise invalid
    seq = int(digits)
    if seq < 1:
        raise invalid
    return seq
