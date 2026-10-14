2026-10-15 | Feed is a full-screen route `/feed` (+ `/feed/new`, `/feed/post/:id`, `/feed/supplier/:id`) linked from the Discover header icon, not a 6th tab | The shell has 5 fixed tabs; avoids touching shared tab pages.
2026-10-15 | Routes/strings registered in module_c via `feedRoutes`/`feedStrings`; follow button + posts link added to supplier_screen | Minimal shared-file edits.
2026-10-15 | Posts carry only `supplier_id`; name/verified badge come from `supplierProvider`, avatar = initials | feed.yaml has no supplier fields or avatar URL.
2026-10-15 | Follow state = membership in GET /v1/feed/following (all pages loaded once, optimistic toggle) | Contract has no per-supplier follow lookup.
2026-10-15 | Canonical posts live in `PostStore`; lists hold ids | A like/comment count change shows in feed, supplier list and detail at once.
2026-10-15 | Composer uses `kind=listing` for uploads and sends the server-relative `/v1/media/files/..` URL | Server rejects other URL shapes (`invalid_media`).
2026-10-15 | Composer gate = `Me.supplierClaimStatus == 'verified'` with a supplier id | Mirrors gateway-verified X-Supplier-Id; server still enforces 403 `supplier_required`.
2026-10-15 | Client screening mirrors server contact regexes (url/email/phone>=9 digits/handle); prohibited-goods list stays server-side | Avoid shipping the Arabic+English banned-term list to the client.
2026-10-15 | Comment authors shown as "You"/"User" | Comment schema has only `user_id`, no display name.
