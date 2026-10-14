from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Kind = Literal["listing", "avatar", "attachment"]
KINDS = ("listing", "avatar", "attachment")


class MediaImage(BaseModel):
    id: str
    url: str
    width: int
    height: int
    bytes: int
    content_type: str
    sha256: str
    kind: Kind
    widths: list[int]
    created_at: datetime
