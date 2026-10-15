# security review 2026-10 k (gateway + media)

Fixed (tests in `services/gateway/tests/test_security_review_k.py`): `HttpGuardMiddleware` skipped GET/HEAD/OPTIONS, but the
proxy buffers every request body, so a GET with a huge (chunked) body bypassed the JSON/media caps. All methods are guarded now.

Verified clean: proxy header allow-list (client X-User-Id/X-Internal-Token/X-Admin-Token/X-Supplier-Id never forwarded, set only
from gateway state); response header allow-list (no Set-Cookie); XFF honoured only from trusted proxies, IPv6 per /64; WS ticket
single-use + TTL (memory and Redis GETDEL); refresh rotation with family revocation on reuse; media magic-byte sniffing + re-encode
(SVG/HTML -> 415), strict id/filename regexes, nosniff + CSP default-src 'none' on all served files, quota checks under per-owner lock.

Open (low, not fixed):
1. Proxy forwards the upstream `Location` header verbatim; an upstream redirect to an internal hostname would leak it.
2. Refresh rotation does not compare the token's access `token_version`; revocation relies on family revocation (logout-all/reset do revoke).
3. WS path check rejects `..` but not empty segments (`//`); upstream messaging must treat them as unknown routes (it does: 404).
4. Media files are served `inline` by design; safe only because every blob is re-encoded to JPEG/PNG/WebP.
