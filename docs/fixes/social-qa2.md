# Social QA pass 2 (feed, media, messaging, assistant)

Fixed in place (tests: `tests/test_concurrency_qa2.py` in feed/media/messaging, `tests/test_injection_qa2.py` in assistant):
- feed: `unlike` answered with the like_count of hidden / held posts (now 404 like `like`).
- messaging: WebSocket `typing` frames kept flowing between two users after one blocked the other; access (incl. blocks) is re-checked before each broadcast, socket closes 4403.
- media: concurrent uploads by one owner could overshoot `max_files_per_user` / byte quota (check-then-insert); `store` now serialises per owner (in-process).
- assistant: downstream strings outside titles reached answers/cards unfiltered (listing unit/source/ids/city/hs_code/source_url/images, trust supplier_id + factor key, shipment reference/status/eta, deal id/status/payment, HS codes). All now go through `Sanitizer` (`ident`, `url`, `loc`).

Open (not fixed):
1. media per-owner quota lock and messaging/feed SQLite serialisation are per process; multi-replica Postgres quota stays best-effort (needs row-level counter or advisory lock).
2. media signing key is random per process when `FF_MEDIA_SIGNING_KEY` is unset (production guard exists; dev only) -> signed links break across replicas.
3. messaging: a blocked user can still read the pre-block history of the thread (by design: they were a participant).
