2026-10-14 | Digest goes only to a verified `digest_email`; new address = pending + 6-digit code (HMAC+salt in table `email_verifications`, 15 min, 5 tries/1 h lock, 3 sends/h/user) | closes security-review-2026-10-b item 1 (mail to unverified address).
2026-10-14 | Legacy unverified `email` in prefs docs is ignored (no data rewrite); `email` kept in API as deprecated alias of `digest_email` | additive contract, no breaking change.
2026-10-14 | No public unsubscribe link; unsubscribe = prefs | avoids unauthenticated state-changing links.
