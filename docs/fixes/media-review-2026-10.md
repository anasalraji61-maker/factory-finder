# media review 2026-10 (QA harden)

Fixed in place (tests in `services/media/tests/test_hardening.py`): PNG `eXIf` orientation now applied; per-user byte quota
(`quota_bytes_exceeded`); bounded concurrent decode; HEAD + single Range on public/private/admin; `no-store` on every error and on
private/admin/sign paths; orphan sweeper (`ff_media.sweep`); contract updated additively (HEAD, 206/416, new 429 code).
Verified clean (no change needed): metadata stripped from JPEG/PNG/WebP originals and variants (public and private), bombs
(IHDR giant, 2^31 canvas, zTXt 100 MB, truncated IDAT, animated), magic/body mismatch, SVG/HTML/GIF/PDF 415, traversal/symlink, signed URL expiry/tamper/cross-file.

Open (not fixed):
1. PDFs are rejected (415), so there is no PDF document path; if verification needs PDFs it requires a new feature (page cap, size cap, reject /JS /JavaScript /OpenAction /Launch /EmbeddedFile, re-render or sanitize) and a malware scanner.
2. Signed URL replay inside the 5 min TTL is possible (bearer link, not single-use); single-use would need a nonce table.
3. Byte quota counts originals only; variants add up to roughly another 1x on disk. Needs a `stored_bytes` column + migration to be exact.
4. Peak memory: a 40 MP RGBA image costs several hundred MB per job (semaphore of 4 bounds it, but set `FF_MEDIA_MAX_PIXELS` lower, e.g. 16000000, on small hosts).
5. ICC profiles are dropped, so wide-gamut (Display P3/AdobeRGB) photos shift color slightly; converting to sRGB before stripping would fix it.
6. Sweeper is local-disk only; S3Storage (unverified) has no `list_keys`; use bucket lifecycle rules there. Deleted images remain in CDN caches for the immutable year.
7. No malware scan or content moderation (already documented in README).
8. Sweep is manual (CLI/cron); there is no scheduled retention for rows whose owner account is gone other than the erase endpoint.
9. Unrelated: `ruff check services` reports 9 errors in services/demand and 2 in services/messaging (other lanes). First e2e/contract_validate run right after contract_check hit a connection-refused / freight admin flake (ports busy from the parallel run); reruns one at a time passed.
