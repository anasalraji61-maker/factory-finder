# Decision: privacy-safe supplier analytics (sourcing)

- 2026-10-15: store only daily per-listing aggregate counters (`listing_stats_daily`), never per-viewer rows. Why: suppliers need funnel numbers; viewers' IPs/ids must not be retained.
- 2026-10-15: viewer identity is a transient HMAC(secret + UTC day, user id or IP) in bounded memory (dedupe 30 min, unique sets capped, 60 events/min per IP and user), wiped on day change. Why: daily rotation makes cross-day tracking impossible; caps bound memory under abuse. Trade-off: unique estimate undercounts when capped, double-counts after a restart, and the multi-day "unique" figure is a sum of daily estimates.
- 2026-10-15: `view` is client-posted (`POST /v1/listings/{id}/events`), not counted on `GET /v1/listings/{id}`. Why: prefetch/bots/cache hits would inflate it and dedupe needs the viewer. `impression` is counted server side on search (raw count, no dedupe).
- 2026-10-15: events for non-countable ids (unknown, unpublished, other sources) answer the same 202 `counted:false`. Why: no existence leak, no row growth for arbitrary ids.
- 2026-10-15: gateway makes `POST /v1/listings/{id}/events` public (optional bearer) and forwards a trusted-proxy-resolved `X-Client-Ip` for that path only. Anonymous browsing is the main traffic source.
- 2026-10-15: watchlist adds are an internal hook only (`Analytics.bump(id, "watchlist_add")`); no HTTP endpoint until notifications and sourcing agree on an internal route (would need `docs/requests/`).
- 2026-10-15: retention 400 days (hourly opportunistic purge); rows deleted with the listing and on account erasure. Aggregates are not part of the user data export (no personal data).
- Known limits: sourcing is per-process (rate/dedupe state is not shared across replicas; counts stay correct, dedupe is per replica). Supplier viewing their own listing is not excluded (gateway does not send X-Supplier-Id on events).
