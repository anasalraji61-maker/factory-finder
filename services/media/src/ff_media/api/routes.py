from __future__ import annotations

import hashlib

from fastapi import APIRouter, Request, Response

from ff_media.errors import BadRequest, MissingUser, NotFound
from ff_media.obs import sanitize_id
from ff_media.schemas import KINDS, MediaImage
from ff_media.service import MediaService
from ff_media.storage.base import EXTS, FILENAME_RE, ID_RE, WIDTHS, make_key
from ff_media.upload import read_upload

router = APIRouter()

CACHE = "public, max-age=31536000, immutable"


def _svc(request: Request) -> MediaService:
    return request.app.state.service


def _user(request: Request) -> str:
    uid = sanitize_id(request.headers.get("x-user-id"))
    if not uid:
        raise MissingUser("X-User-Id header is required")
    return uid


@router.post("/v1/media/images", status_code=201, response_model=MediaImage)
async def upload_image(request: Request, response: Response) -> MediaImage:
    owner = _user(request)
    svc = _svc(request)
    await svc.charge_hourly(owner)
    up = await read_upload(request, svc.settings.max_upload_bytes)
    if up.kind is not None and up.kind not in KINDS:
        raise BadRequest("`kind` must be listing, avatar or attachment", {"allowed": list(KINDS)})
    image, created = await svc.store(owner, up.kind or "listing", up.data)
    if not created:
        response.status_code = 200
    return image


@router.delete("/v1/media/images/{media_id}", status_code=204)
async def delete_image(media_id: str, request: Request) -> Response:
    owner = _user(request)
    if not ID_RE.fullmatch(media_id):
        raise NotFound("Image not found")
    await _svc(request).delete(owner, media_id)
    return Response(status_code=204)


@router.get("/v1/media/files/{filename}")
async def get_file(filename: str, request: Request, w: int | None = None) -> Response:
    m = FILENAME_RE.fullmatch(filename)
    if not m:
        raise NotFound("Image not found")
    media_id, ext = m.groups()
    if w is not None and w not in WIDTHS:
        raise BadRequest("`w` must be one of 200, 400, 800", {"allowed": list(WIDTHS)})
    storage = _svc(request).storage
    data = await storage.get(make_key(media_id, ext, w)) if w is not None else None
    if data is None:  # no such variant (original is not wider than w) -> the original
        data = await storage.get(make_key(media_id, ext))
        w = None
    if data is None:
        raise NotFound("Image not found")
    etag = '"' + hashlib.sha256(data).hexdigest()[:32] + '"'
    headers = {
        "Cache-Control": CACHE, "ETag": etag, "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'", "Cross-Origin-Resource-Policy": "cross-origin",
        "Content-Disposition": f'inline; filename="{media_id}.{ext}"',
    }  # fmt: skip
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(data, media_type=EXTS[ext], headers=headers)
