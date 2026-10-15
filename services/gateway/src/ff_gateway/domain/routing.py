"""Path-prefix routing table and public/protected policy (pure)."""

import re

PREFIX_TO_UPSTREAM: dict[str, str] = {
    "/v1/search": "sourcing", "/v1/listings": "sourcing", "/v1/suppliers": "sourcing",
    "/v1/categories": "sourcing", "/v1/sources": "sourcing", "/v1/my": "sourcing",
    "/v1/recommendations": "sourcing",
    "/v1/quotes": "logistics", "/v1/fx": "logistics", "/v1/carriers": "logistics", "/v1/hs": "logistics",
    "/v1/compliance": "logistics",
    "/v1/countries": "geo", "/v1/cities": "geo", "/v1/hubs": "geo", "/v1/distance": "geo",
    "/v1/trust": "trust",
    "/v1/requests": "rfq", "/v1/offers": "rfq", "/v1/deals": "rfq", "/v1/reviews": "rfq",
    "/v1/conversations": "messaging",
    "/v1/shipments": "tracking", "/v1/validate": "tracking",
    "/v1/watchlist": "notifications", "/v1/alerts": "notifications", "/v1/devices": "notifications",
    "/v1/notification-prefs": "notifications",
    "/v1/assistant": "assistant",
    "/v1/invoices": "payments", "/v1/ledger": "payments", "/v1/payments": "payments",
    "/v1/media": "media",
    "/v1/feed": "feed",
    "/v1/freight": "freight",
}  # fmt: skip

PUBLIC_GET_PREFIXES = (
    "/v1/search", "/v1/listings", "/v1/suppliers", "/v1/categories", "/v1/recommendations",
    "/v1/countries", "/v1/cities", "/v1/hubs", "/v1/fx/rates", "/v1/hs", "/v1/compliance",
    "/v1/media/files",  # image bytes only; upload/delete (/v1/media/images) stay authenticated
    "/v1/media/private",  # private files: media itself requires the owner's X-User-Id (optional bearer here) or a valid signed URL
)  # fmt: skip
PUBLIC_EXACT = {("POST", "/v1/quotes/landed-cost"), ("POST", "/v1/compliance/checklist"), ("GET", "/v1/feed/trending")}  # trending: anonymous browsing; identity optional


# Service-to-service endpoints that must never be reachable through the public gateway
# (the gateway attaches the internal token, so exposing them would bypass their guard).
INTERNAL_ONLY = (("POST", "/v1/alerts/evaluate"), ("POST", "/v1/alerts/digest"))


# Public verified-business badge (GET only); the rest of /v1/trust stays authenticated.
TRUST_BADGE_PATH = re.compile(r"^/v1/trust/suppliers/[^/]+/verification\Z")


def is_trust_verification_write_path(path: str) -> bool:
    """Supplier-only verification endpoints (need a verified supplier claim)."""
    return _under(path.rstrip("/") or "/", "/v1/trust/verification")


def is_internal_only(method: str, path: str) -> bool:
    path = path.rstrip("/") or "/"
    if _under(path, "/v1/media/admin"):  # media's admin read is reachable only via /v1/admin/media/* (gateway-held token)
        return True
    return (method.upper(), path) in INTERNAL_ONLY


# Anonymous listing analytics events (view / contact_click / share); identity optional, see sourcing analytics.
LISTING_EVENTS_PATH = re.compile(r"^/v1/listings/[A-Za-z0-9_.:\-]{1,64}/events\Z")


def is_listing_events(method: str, path: str) -> bool:
    return method.upper() == "POST" and bool(LISTING_EVENTS_PATH.match(path.rstrip("/") or "/"))


# Supplier review reads live in rfq although /v1/suppliers belongs to sourcing (public GETs, see PUBLIC_GET_PREFIXES).
RFQ_SUPPLIER_PATH = re.compile(r"^/v1/suppliers/[^/]+/(reviews|review-summary)\Z")


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def resolve_upstream(path: str) -> str | None:
    if RFQ_SUPPLIER_PATH.match(path.rstrip("/") or "/"):
        return "rfq"
    for prefix, name in PREFIX_TO_UPSTREAM.items():
        if _under(path, prefix):
            return name
    return None


def matched_prefix(path: str) -> str | None:
    """Routing-table prefix for a path (low-cardinality label for logs)."""
    if RFQ_SUPPLIER_PATH.match(path.rstrip("/") or "/"):
        return "/v1/suppliers/{ref}/reviews"
    return next((p for p in PREFIX_TO_UPSTREAM if _under(path, p)), None)


def is_public(method: str, path: str) -> bool:
    path = path.rstrip("/") or "/"
    if path == "/health" or _under(path, "/v1/auth"):
        return True
    if (method.upper(), path) in PUBLIC_EXACT or is_listing_events(method, path):
        return True
    if method.upper() in ("GET", "HEAD") and TRUST_BADGE_PATH.match(path):
        return True
    return method.upper() in ("GET", "HEAD") and any(_under(path, p) for p in PUBLIC_GET_PREFIXES)
