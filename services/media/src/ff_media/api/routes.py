from __future__ import annotations

import hashlib
import hmac

from fastapi import APIRouter, Request, Response

from ff_media.errors import AdminRequired, BadRequest, MissingUser, NotFound
from ff_media.obs import sanitize_id
from ff_media.schemas import KINDS, VISIBILITIES, MediaImage, SignedUrl
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
        raise BadRequest("`kind` must be listing, avatar, attachment or verification", {"allowed": list(KINDS)})
    kind = up.kind or "listing"
    if up.visibility is not None and up.visibility not in VISIBILITIES:
        raise BadRequest("`visibility` must be public or private", {"allowed": list(VISIBILITIES)})
    if kind == "verification" and up.visibility == "public":
        raise BadRequest("kind=verification files are always private")
    visibility = "private" if kind == "verification" else (up.visibility or "public")
    image, created = await svc.store(owner, kind, up.data, visibility)
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


PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'", "Cross-Origin-Resource-Policy": "same-site",
    "Referrer-Policy": "no-referrer", "Pragma": "no-cache",
}  # fmt: skip


def _private_response(row, data: bytes) -> Response:
    headers = {**PRIVATE_HEADERS, "Content-Disposition": f'inline; filename="{row.id}.{row.ext}"'}
    return Response(data, media_type=EXTS[row.ext], headers=headers)


@router.post("/v1/media/files/{media_id}/sign", response_model=SignedUrl)
async def sign_private(media_id: str, request: Request) -> Response:
    """Owner only: a 5-minute signed URL for one of their private files (404 for anyone else)."""
    owner = _user(request)
    if not ID_RE.fullmatch(media_id):
        raise NotFound("File not found")
    signed = await _svc(request).sign_url(owner, media_id)
    return Response(signed.model_dump_json(), media_type="application/json", headers={"Cache-Control": "private, no-store"})


@router.get("/v1/media/private/{filename}")
async def get_private(
    filename: str, request: Request, u: str | None = None, exp: str | None = None, sig: str | None = None,
) -> Response:  # fmt: skip
    m = FILENAME_RE.fullmatch(filename)
    if not m:
        raise NotFound("File not found")
    viewer = sanitize_id(request.headers.get("x-user-id"))
    row, data = await _svc(request).read_private(m.group(1), m.group(2), viewer, u, exp, sig)
    return _private_response(row, data)


@router.get("/v1/media/admin/files/{name}")
async def admin_get(name: str, request: Request) -> Response:
    """Admin read (gateway passthrough injects the service admin token). 404 when no admin token is configured."""
    svc = _svc(request)
    token = svc.settings.admin_token.get_secret_value() if svc.settings.admin_token else ""
    if not token:
        raise NotFound("Not Found")
    given = request.headers.get("x-admin-token", "")
    if not hmac.compare_digest(given.encode(), token.encode()):
        raise AdminRequired("Valid X-Admin-Token required")
    media_id = name.split(".", 1)[0]
    if not ID_RE.fullmatch(media_id) or (name != media_id and not FILENAME_RE.fullmatch(name)):
        raise NotFound("File not found")
    row, data = await svc.read_admin(media_id)
    return _private_response(row, data)
