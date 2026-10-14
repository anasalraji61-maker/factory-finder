from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Kind = Literal["listing", "avatar", "attachment", "verification"]
KINDS = ("listing", "avatar", "attachment", "verification")
VISIBILITIES = ("public", "private")


class MediaImage(BaseModel):
    id: str
    url: str
    width: int
    height: int
    bytes: int
    content_type: str
    sha256: str
    kind: Kind
    visibility: Literal["public", "private"] = "public"
    widths: list[int]
    created_at: datetime


class SignedUrl(BaseModel):
    url: str
    expires_at: datetime
    ttl_seconds: int
