# mobile-live: seed needs for scripts/serve_stack.py (owner: stack script)

- Freight forwarders: no approved forwarder is seeded, so `inbox()` / `myQuotes()` (forwarder side) and
  quote comparison with real quotes cannot be live-tested. Need: a third user "forwarder" with an approved
  application, plus one quote on `freight_request_id`; expose `forwarder` user token and `freight_quote_id` in the info file.
- Reviews: no review is seeded, so only empty-summary parsing is covered. Need: one review on `claimed_supplier_id`
  (needs a completed deal) to cover histogram/sub-ratings/list items.
- Analytics: no events are seeded, so counts are all zero. Need: a few POSTed listing events for `native_listing_id`.
