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


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None | str:
    """None = no/ignorable Range header (serve 200); 'bad' = unsatisfiable (416); else inclusive (start, end).
    Only a single ``bytes=a-b`` / ``a-`` / ``-n`` range is honoured; multi-range requests are served whole."""
    if not header or not header.lower().startswith("bytes=") or "," in header:
        return None
    spec = header[6:].strip()
    a, sep, b = spec.partition("-")
    if (
        not sep
        or not (a.isascii() and b.isascii())
        or not (a.isdigit() or a == "")
        or not (b.isdigit() or b == "")
        or (a == "" and b == "")
    ):
        return None
    # a number longer than 18 digits exceeds any real size; clamp it (int() raises past 4300 digits -> would be a 500)
    a, b = ("9" * 18 if len(a) > 18 else a), ("9" * 18 if len(b) > 18 else b)
    if a == "":  # suffix
        n = int(b)
        if n == 0:
            return "bad"
        return max(0, size - n), size - 1
    start = int(a)
    end = min(int(b), size - 1) if b else size - 1
    if start >= size or end < start:
        return "bad"
    return start, end


def _body_response(
    request: Request, data: bytes, media_type: str, headers: dict[str, str]
) -> Response:
    """200/206/416 with HEAD support (headers only, true Content-Length) and single-range handling."""
    headers = {**headers, "Accept-Ranges": "bytes"}
    rng = _parse_range(request.headers.get("range"), len(data))
    status, body = 200, data
    if rng == "bad":
        return Response(
            status_code=416, headers={**headers, "Content-Range": f"bytes */{len(data)}"}
        )
    if isinstance(rng, tuple):
        status, body = 206, data[rng[0] : rng[1] + 1]
        headers["Content-Range"] = f"bytes {rng[0]}-{rng[1]}/{len(data)}"
    if request.method == "HEAD":
        return Response(
            status_code=status,
            media_type=media_type,
            headers={**headers, "Content-Length": str(len(body))},
        )
    return Response(body, status_code=status, media_type=media_type, headers=headers)


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
        raise BadRequest(
            "`kind` must be listing, avatar, attachment or verification", {"allowed": list(KINDS)}
        )
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


@router.head("/v1/media/files/{filename}", operation_id="headImageFile")
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
    return _body_response(request, data, EXTS[ext], headers)


PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'", "Cross-Origin-Resource-Policy": "same-site",
    "Referrer-Policy": "no-referrer", "Pragma": "no-cache",
}  # fmt: skip


def _private_response(request: Request, row, data: bytes) -> Response:
    headers = {**PRIVATE_HEADERS, "Content-Disposition": f'inline; filename="{row.id}.{row.ext}"'}
    return _body_response(request, data, EXTS[row.ext], headers)


@router.post("/v1/media/files/{media_id}/sign", response_model=SignedUrl)
async def sign_private(media_id: str, request: Request) -> Response:
    """Owner only: a 5-minute signed URL for one of their private files (404 for anyone else)."""
    owner = _user(request)
    if not ID_RE.fullmatch(media_id):
        raise NotFound("File not found")
    signed = await _svc(request).sign_url(owner, media_id)
    return Response(
        signed.model_dump_json(),
        media_type="application/json",
        headers={"Cache-Control": "private, no-store"},
    )


@router.head("/v1/media/private/{filename}", operation_id="headPrivateFile")
@router.get("/v1/media/private/{filename}")
async def get_private(
    filename: str, request: Request, u: str | None = None, exp: str | None = None, sig: str | None = None,
) -> Response:  # fmt: skip
    m = FILENAME_RE.fullmatch(filename)
    if not m:
        raise NotFound("File not found")
    viewer = sanitize_id(request.headers.get("x-user-id"))
    row, data = await _svc(request).read_private(m.group(1), m.group(2), viewer, u, exp, sig)
    return _private_response(request, row, data)


@router.head("/v1/media/admin/files/{name}", operation_id="headAdminFile")
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
    return _private_response(request, row, data)


@router.post("/v1/internal/users/{user_id}/export")
async def export_user(user_id: str, request: Request) -> dict:
    return {"service": "media", "user_id": user_id, **await _svc(request).export_owner(user_id)}


@router.delete("/v1/internal/users/{user_id}/data")
async def erase_user(user_id: str, request: Request) -> dict:
    return {
        "service": "media",
        "user_id": user_id,
        "status": "done",
        "counts": await _svc(request).erase_owner(user_id),
    }
