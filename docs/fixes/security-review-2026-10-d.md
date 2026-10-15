# Security review 2026-10-d (feed, freight, trust verification, admin passthroughs, licensed feeds, assistant, messaging)

## Fixed in place (tests: `services/{feed,freight,sourcing,gateway,messaging,logistics}/tests/*security_review_d*` and test_api/test_quotes additions)
- **Gateway path-policy bypass**: httpx collapses `/./` upstream, so `POST /v1/alerts/./evaluate` skipped the exact-match
  internal-only block (a logged-in user could trigger evaluate/digest for everybody; the gateway adds the internal token), and
  `/v1/feed/./posts`, `/v1/freight/./applications` skipped the verified-email gate. Proxy now rejects `.` as well as `..` (400).
- **Freight bait-and-switch**: a forwarder could revise a quote between the buyer's comparison and the accept. `POST /quotes/{id}/accept`
  now takes an optional `{"revision": n}` (additive, contract updated); mismatch -> 409 `quote_changed`. The accept also CASes the
  quote row on `status=submitted AND revision=<read>` so a concurrent revise/withdraw cannot slip in.
- **Hostile keyset cursors -> 500** (feed, freight): `t` near year 1/9999 with a tz offset overflowed `astimezone`, and `s` > int64 overflowed
  the DB driver. Both now 422 `invalid_cursor`.
- **Messaging `attachments[]` accepted any host** when `media_allowed_hosts` was empty (attacker host + media-shaped path). Absolute URLs
  now need an explicitly configured host; empty = relative `/v1/media/files/...` only.
- **Assistant deal tool** failed open when the deal response carried no party ids; now denies unless the caller is buyer or supplier.
- **Licensed REST adapter**: provider response now streamed with an 8 MiB cap; `url` kept only if http(s) (no `javascript:`); `id` must be a
  plain token (it becomes `/v1/listings/{id}`); title/supplier name length-capped (dedupe is O(n^2) on titles).
- **Email screening regex was quadratic** (~0.2 s CPU for a 2 kB body on the event loop in feed/freight/sourcing/rfq). Anchored with a
  lookbehind; detection and redaction unchanged.
- **`hmac.compare_digest(str, str)` raised TypeError (500) on a non-ASCII `X-Internal-Token`** in 11 services; now compares bytes (401).

Verified OK (no change): gateway admin passthroughs (`hmac.compare_digest`, 404 when unset, fixed method/path allow-list, `_seg`, query allow-list,
no client identity/admin headers forwarded); trust verification (owner scoping by gateway-verified `X-Supplier-Id`, other suppliers' docs 404,
state machine incl. terminal states, HMAC fingerprints, number never stored/returned, media path validation, rate limit); freight authz
(buyer/forwarder/winner views, 404 for non-parties, no `buyer_id` to losers); feed authz (owner-only delete, supplier-only post).

## Open (design / needs product decision)
1. MEDIUM - FIXED 2026-10-15 (see docs/decisions/media-private.md; partly mitigated 2026-10-15: trust rejects, 409 `file_in_use`, a media file already attached to another supplier's document; true uploader check needs media, see docs/requests/trust-media-ownership.md; old public copies must be re-uploaded). **Verification documents are publicly readable.** Files are uploaded through media, whose `GET /v1/media/files/*` is public
   (unguessable id only). Business licences / bank references need a private bucket class or signed, short-lived, admin-only URLs.
   Owner: media + trust. Also a supplier can reference any other media file id (no ownership link between uploader and document).
2. MEDIUM - MITIGATED 2026-10-15 (docs/decisions/freight-anti-abuse.md: rating only after `rating_min_delay_seconds` (24 h) past close, max 2 ratings per buyer/forwarder pair per 365 d; real fix still needs payment/tracking evidence). **Freight ratings can be farmed**: award -> close -> rate has no proof of shipment/payment; a forwarder with a sock-puppet buyer
   account can mint 5-star ratings (rate limited 20/h, one per request). Needs payment/escrow or tracking evidence before a rating counts.
3. LOW - FIXED for freight 2026-10-15 (reports count toward auto-hide only from accounts older than `report_min_account_age_seconds` (24 h); awarded requests are never auto-hidden); feed FIXED 2026-10-15 too (`FF_FEED_REPORT_MIN_ACCOUNT_AGE_SECONDS`, default 86400, age = first activity in the feed service). Feed/freight auto-hide at 3 distinct reporters: three throwaway accounts can hide a competitor's post (feed has no eligibility
   filter; freight limits reporters to parties). Add account-age / verified-email requirement for reports.
4. LOW - FIXED 2026-10-15 (feed `delete_post`/`delete_comment` keep report rows; admin /reports still lists them. Post body is not snapshotted). A supplier can delete a hidden/reported post or comment, destroying the report evidence (`delete_post` removes its reports).
   Soft-delete or keep an audit copy.
5. LOW - Feed comments expose the commenter's `user_id` to every user; replace with a `mine` flag + display name if ids are sensitive.
6. LOW - Messaging legacy `attachment` (single URL) still allows any https host by default (`attachment_allowed_hosts` empty): a phishing
   link can be sent as a "file". Set the allow-list in production or deprecate it in favour of `attachments[]`.
7. LOW - Admin actions on feed/freight (hide, suspend, approve) have no audit log (trust verification does); reasons are stored on the row only.
8. LOW - Per-process state again: assistant quota, trust verification store and its rate limit, sourcing caches (see 2026-10 item 4).
   Trust verification store is process-local (documents lost on restart) until the DB-backed store lands.
9. INFO - Freight `apply` pending-check and quote-count caps are check-then-insert (small overshoot under concurrency; bounded by rate limits).
10. INFO - Per-request regex/banned-term screening of a 2.2 kB feed post still costs ~100 ms CPU (banned-term scan, linear but with ~1k terms)
   on the event loop; bounded by the per-user post/comment rate limits. Move to a thread or an Aho-Corasick index if it shows up in profiles.
