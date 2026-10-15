2026-10-15 | Listing events are reported through `ListingEventReporter` (fire-and-forget, deduped per listing+type per session, nothing sent in mock mode) | keeps the UI unblocked and matches the server's 30-minute dedupe.
2026-10-15 | "Share" on listing detail copies the listing text/link to the clipboard and counts a `share` event | no share plugin is allowed in docs/AGENTS.md dependency list.
2026-10-15 | Analytics chart uses its own zero-based painter/math (`analytics_logic.dart`) instead of reco `chart_math.dart` | the reco helper scales between min and max price; counts must start at zero.
2026-10-15 | Analytics route is `/my-products/analytics[?listing_id=]`, registered before `/my-products/:id` | otherwise the editor route would capture it.
