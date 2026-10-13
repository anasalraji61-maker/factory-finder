2026-10-13 | Mock timeline anchored on shipment registration time (start = anchor - 1..240h), pure function of reference | deterministic, progresses with `now`
2026-10-13 | Shipment aggregate stored as JSON in one SQLAlchemy table (indexed owner/status) | simple, provider data is replaced wholesale on refresh
2026-10-13 | Other users' shipments answer 404 (not 403); duplicates per (user, type, normalized ref) -> 409 | no id leakage
2026-10-13 | Creation counts as a refresh for throttling (default 60 s, `Retry-After` header) | protects paid provider quotas
2026-10-13 | `progress_percent` derived from status via fixed milestone table | provider-independent
