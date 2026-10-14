"""Request bodies (extra fields are rejected) and shared patterns."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ff_feed.moderation import REPORT_REASONS

USER_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")
SUPPLIER_RE = re.compile(r"^sup_[A-Za-z0-9_.:\-]{1,59}$")
ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,40}$")
LISTING_RE = r"^[A-Za-z0-9_.:\-]{1,64}$"
TAG_RE = re.compile(r"^[\w\-]{1,30}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

MAX_POST_CHARS = 2000
MAX_COMMENT_CHARS = 500
MAX_MEDIA = 5
MAX_TAGS = 5


def _clean(v: str) -> str:
    v = v.strip()
    if _CONTROL.search(v):
        raise ValueError("control characters are not allowed")
    return v


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PostCreate(_Body):
    body: Annotated[str, Field(min_length=1, max_length=MAX_POST_CHARS + 200)]
    media: Annotated[list[Annotated[str, Field(min_length=1, max_length=300)]], Field(max_length=MAX_MEDIA)] = []
    tags: Annotated[list[Annotated[str, Field(min_length=1, max_length=40)]], Field(max_length=MAX_TAGS)] = []
    listing_ref: Annotated[str | None, Field(pattern=LISTING_RE)] = None

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        v = _clean(v)
        if not v or len(v) > MAX_POST_CHARS:
            raise ValueError(f"body must be 1-{MAX_POST_CHARS} characters")
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for raw in v:
            t = raw.strip().lstrip("#").lower()
            if not TAG_RE.match(t):
                raise ValueError("tags are 1-30 letters, digits, '_' or '-'")
            if t not in out:
                out.append(t)
        return out


class CommentCreate(_Body):
    body: Annotated[str, Field(min_length=1, max_length=MAX_COMMENT_CHARS + 100)]

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        v = _clean(v)
        if not v or len(v) > MAX_COMMENT_CHARS:
            raise ValueError(f"body must be 1-{MAX_COMMENT_CHARS} characters")
        return v


class ReportIn(_Body):
    reason: Literal[REPORT_REASONS]  # type: ignore[valid-type]
    details: Annotated[str | None, Field(max_length=300)] = None


class HideIn(_Body):
    reason: Annotated[str, Field(min_length=3, max_length=300)]

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = _clean(v)
        if len(v) < 3:
            raise ValueError("reason too short")
        return v
