"""Path-prefix routing table and public/protected policy (pure)."""

PREFIX_TO_UPSTREAM: dict[str, str] = {
    "/v1/search": "sourcing", "/v1/listings": "sourcing", "/v1/suppliers": "sourcing",
    "/v1/categories": "sourcing", "/v1/sources": "sourcing",
    "/v1/quotes": "logistics", "/v1/fx": "logistics", "/v1/carriers": "logistics",
    "/v1/countries": "geo", "/v1/cities": "geo", "/v1/hubs": "geo", "/v1/distance": "geo",
    "/v1/trust": "trust",
    "/v1/requests": "rfq", "/v1/offers": "rfq", "/v1/deals": "rfq",
    "/v1/conversations": "messaging",
    "/v1/shipments": "tracking", "/v1/validate": "tracking",
    "/v1/watchlist": "notifications", "/v1/alerts": "notifications", "/v1/devices": "notifications",
    "/v1/assistant": "assistant",
}  # fmt: skip

PUBLIC_GET_PREFIXES = (
    "/v1/search", "/v1/listings", "/v1/suppliers", "/v1/categories",
    "/v1/countries", "/v1/cities", "/v1/hubs", "/v1/fx/rates",
)  # fmt: skip
PUBLIC_EXACT = {("POST", "/v1/quotes/landed-cost")}


# Service-to-service endpoints that must never be reachable through the public gateway
# (the gateway attaches the internal token, so exposing them would bypass their guard).
INTERNAL_ONLY = (("POST", "/v1/alerts/evaluate"),)


def is_internal_only(method: str, path: str) -> bool:
    path = path.rstrip("/") or "/"
    return (method.upper(), path) in INTERNAL_ONLY


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def resolve_upstream(path: str) -> str | None:
    for prefix, name in PREFIX_TO_UPSTREAM.items():
        if _under(path, prefix):
            return name
    return None


def is_public(method: str, path: str) -> bool:
    path = path.rstrip("/") or "/"
    if path == "/health" or _under(path, "/v1/auth"):
        return True
    if (method.upper(), path) in PUBLIC_EXACT:
        return True
    return method.upper() in ("GET", "HEAD") and any(_under(path, p) for p in PUBLIC_GET_PREFIXES)
