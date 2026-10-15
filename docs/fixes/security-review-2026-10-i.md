# Security review 2026-10-i (independent reviewer)

Scope: code added in the last day. Result: 2 real ReDoS defects (fixed), 1 unbounded-input hardening (fixed), no authz/injection defects found.

## Fixed
1. **tracking `parse_ts`** (`domain/normalize.py`): `re.sub(r"\s*(?:UTC|GMT)$", ...)` is O(n^2) on whitespace runs (6.3 s at 20 kB, provider-controlled text). Replaced by a suffix check plus a 64-char cap.
2. **tracking `clean_vessel_name` / `parse_vessel`** (`domain/validators.py`): `_NAME_IMO` (`\(?\s*IMO...`) is O(n^2) on whitespace (5.4 s at 20 kB). Input capped at 300 chars before any regex.
3. **sourcing `parse_price_text`** (`domain/pricing.py`): no input cap; several patterns (`_INT`/`_QTY_*`/`_PER`) are superlinear (0.7 s at 20 kB, minutes at MB scale; provider responses may be 8 MB). Capped at 500 chars.
Tests: `services/{tracking,sourcing,geo}/tests/test_security_review_i.py` (timing guards).

## Reviewed, no defect
- gateway claim approve/reject/revoke/audit: admin token constant-time, reviewer label charset-restricted (header injection impossible), reason bounded; trust release URL uses supplier_id validated by `^sup_[A-Za-z0-9_.:-]{1,59}$` and a fixed upstream base (no SSRF); client headers are allow-listed, X-Supplier-Id only from DB when verified.
- admin passthroughs (trust/freight/feed/payments): method+path allow-list, id regexes use `\Z`, query allow-list, no client admin/identity headers forwarded.
- payments review/late-payment routes: `admin_only` (compare_digest); late scan only flags, never pays; tx already bound to another invoice is skipped.
- rfq invites: invite-only enforced on list/get/offers/create-offer; invite ids validated; X-Supplier-Id comes from the gateway only.
- assistant rfq_draft: `deep_link` is a constant; mobile acts only on exactly `/requests/new`, re-validates every prefill value, ids pass `_safeId` and are URL-encoded.
- mobile `sanitizeReturnPath`: single leading `/`, no scheme/authority/backslash/whitespace/bad %-escapes, auth-loop guard. In-app routing only.
- media: Range parser single-range, digit-only, clamped (no 500/amplification); private files use a distinct `p-` key unreachable by the public route; signed URLs HMAC, owner-bound, TTL-bounded, constant-time; upload capped streaming.
- geo fuzzy search: query <= 100 chars, OSA early-exit on length gap; worst case measured ~0.1 s.

## Minor / not fixed
- media `_parse_range`: a >18-digit zero-padded start is clamped to 9s (416 instead of 206); size-0 suffix range yields a malformed Content-Range. Not security relevant.
- sourcing `licensed_rest.py` has a pre-existing unused import (ruff F401), not from this review.
