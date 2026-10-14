# media (port 8112)

Image upload and serving for listing photos, avatars and message attachments. Reached through the gateway at
`/v1/media` (POST/DELETE need a bearer token; **GET `/v1/media/files/{id}.{ext}` is public**, but PRIVATE files are never served there).

- Run: `uvicorn ff_media.main:app --port 8112`; tests: `../../.venv/bin/python -m pytest -q`
- Contract: `contracts/openapi/media.yaml`. `X-User-Id` required on POST/DELETE (401); `X-Internal-Token` checked only when `FF_INTERNAL_TOKEN` is set (not for `/health`, `/ready`).
- Upload: `POST /v1/media/images`, multipart field `file` (+ optional `kind=listing|avatar|attachment|verification`, `visibility=public|private`) -> 201 `{id,url,width,height,bytes,content_type,sha256,kind,widths,created_at}` (200 when the same image was already uploaded by that user).
- Validation: format by MAGIC BYTES only (jpeg/png/webp; svg, html, gif, anything else -> 415, client content-type and filename ignored); size cap enforced while streaming (413); width/height cap and total pixel cap before decoding (422); corrupt images 422.
- Re-encode: every image is decoded and re-encoded into a fresh image (EXIF incl. GPS, ICC, XMP, PNG text dropped; EXIF orientation applied first; animated input keeps frame 1). Variants 200/400/800 px wide are generated for widths smaller than the original; `?w=` accepts only those values (others 422), falling back to the original when no variant exists.
- Ids: 128-bit random hex. Files: `GET /v1/media/files/<id>.<ext>` -> immutable cache headers, ETag/304, `X-Content-Type-Options: nosniff`, CSP `default-src 'none'`. Names are regex-validated and storage paths must resolve inside the storage root.
- Ownership: owner = `X-User-Id`; `DELETE /v1/media/images/{id}` by anyone else is 404 (never 403). Deleted images can live on in downstream caches for the immutable lifetime (use a CDN purge if that matters).
- Private files (`visibility=private`, or `kind=verification` which is always private; `kind=verification`+`visibility=public` -> 422): stored under `p-` keys the public route cannot address (public `GET /v1/media/files/*` -> 404), no resized variants, response `url` is the relative ref `/v1/media/private/<id>.<ext>`. Readable by the owner (`X-User-Id`) at that path, by anyone with a signed URL (`POST /v1/media/files/{id}/sign`, owner only -> `?u=&exp=&sig=`, HMAC-SHA256 over id+user+exp, 5 min, constant-time compare, bound to the file's owner) and by admins via `GET /v1/media/admin/files/{id}` (X-Admin-Token; gateway: `/v1/admin/media/files/{id}`). All other cases are one 404. Headers: `Cache-Control: private, no-store`, nosniff, `Referrer-Policy: no-referrer`, CSP. No listing. Dedupe is per (owner, hash, visibility). Rows created before migration 0002 are public; re-upload old verification documents.
- Quotas per user: 200 stored files, 30 upload requests per rolling hour (every request counts, valid or not; 429 + `Retry-After`).
- Dedupe: per owner by SHA-256 of the re-encoded bytes.
- Storage: `StorageBackend` protocol (`storage/base.py`); `LocalDiskStorage` (default; keep `FF_MEDIA_STORAGE_ROOT` on a persistent volume) and `S3Storage` (UNVERIFIED skeleton, off by default, needs `pip install .[s3]`; credentials only from the environment).
- Nothing is scanned for malware and no content moderation is performed; add both before opening uploads to untrusted users at scale.

| Env | Default |
|---|---|
| `FF_MEDIA_PUBLIC_BASE_URL` | unset -> relative `/v1/media/files/...`; set to the PUBLIC gateway origin (e.g. `https://api.example.com`) so images can be referenced by absolute URL |
| `FF_MEDIA_STORAGE_BACKEND` | `local` (`s3`) |
| `FF_MEDIA_STORAGE_ROOT` | `./media-data` |
| `FF_MEDIA_S3_BUCKET` / `_REGION` / `_ENDPOINT_URL` / `_PREFIX` | unset / unset / unset / `media/` |
| `FF_MEDIA_S3_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` | unset (env only) |
| `FF_MEDIA_SIGNING_KEY` | unset -> random per-process key (dev); **required when FF_ENV=production** (refuses to start) |
| `FF_MEDIA_SIGNED_URL_TTL_SECONDS` | `300` |
| `FF_MEDIA_ADMIN_TOKEN` | unset -> admin read 404 (gateway must hold the same value) |
| `FF_MEDIA_MAX_UPLOAD_BYTES` | `5242880` |
| `FF_MEDIA_MAX_DIMENSION` / `_MAX_PIXELS` | `8000` / `40000000` |
| `FF_MEDIA_JPEG_QUALITY` | `85` |
| `FF_MEDIA_MAX_FILES_PER_USER` / `_MAX_UPLOADS_PER_HOUR` | `200` / `30` |
| `FF_MEDIA_DATABASE_URL` / `_DB_AUTO_CREATE` | `sqlite+aiosqlite:///./media.db` / auto (see docs/DB.md) |

## Ops (logging / readiness)
`GET /ready`: 503 when the database is unreachable or storage is not writable. One JSON log line per request (route template, status, duration, user id); never query strings, bodies or tokens. Code: `obs.py` (self-contained copy). Migrations: `alembic upgrade head` (see docs/DB.md).
