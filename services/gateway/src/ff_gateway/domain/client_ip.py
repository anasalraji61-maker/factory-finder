"""Trustworthy client IP resolution behind reverse proxies (pure)."""

import ipaddress
from collections.abc import Sequence

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_networks(csv: str) -> list[Network]:
    """Comma-separated CIDRs / bare IPs -> networks. Raises ValueError on garbage (fail at startup)."""
    return [ipaddress.ip_network(p.strip(), strict=False) for p in csv.split(",") if p.strip()]


def _ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _trusted(ip, nets: Sequence[Network]) -> bool:
    return any(ip in n for n in nets if n.version == ip.version)


def client_ip(peer: str | None, xff: str | None, trusted: Sequence[Network]) -> str:
    """The direct peer, unless the peer is a trusted proxy: then the right-most X-Forwarded-For
    entry that is not itself a trusted proxy (entries further left are client-controlled)."""
    if not peer:
        return "unknown"
    p = _ip(peer)
    if p is None or not trusted or not xff or not _trusted(p, trusted):
        return peer
    hops = [h.strip() for h in xff.split(",")]
    for raw in reversed(hops):
        ip = _ip(raw)
        if ip is None:
            return peer  # malformed chain: do not guess
        if not _trusted(ip, trusted):
            return str(ip)
    return str(_ip(hops[0]) or peer)  # every hop is a trusted proxy: leftmost is the origin
