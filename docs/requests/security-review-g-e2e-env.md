New optional env vars (all have safe defaults; scripts/e2e.py needs none):
- FF_TRACKING_MAX_SHIPMENTS_PER_USER (default 200) - e2e creating >200 shipments per user would get 409 shipment_limit_reached.
- FF_TRACKING_OUTBOX_RETENTION_DAYS (default 30).
Behavioural change for e2e: a supplier may have at most 5 active offers per request (409 offer_limit_reached).
