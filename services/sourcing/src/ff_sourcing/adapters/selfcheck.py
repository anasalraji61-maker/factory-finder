"""Owner-run field-coverage self-check for ONE real adapter.

    FF_SOURCING_SELFCHECK_CONFIRM=1 python -m ff_sourcing.adapters.selfcheck <adapter_id> [query]

Guards (all must hold, otherwise nothing is sent):
  * FF_SOURCING_SELFCHECK_CONFIRM=1 is set explicitly (never implied by anything else);
  * neither the global kill switch (FF_SOURCING_KILL_SWITCH) nor the adapter's own
    (FF_SOURCING_<ID>_DISABLED) is on; if the kill switch is on the check stops;
  * the adapter's credentials/config are present in the environment.
It performs exactly ONE low-volume search (limit 5) through the adapter's normal, rate-limited,
robots-aware path (public-page mode adds one robots.txt request), then prints which normalised Listing
fields were populated. Nothing is stored, no adapter is enabled, and credentials are never printed
(error text is scrubbed of every secret value in the environment).
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from ..config import Settings
from ..domain.models import ListingDetail, SearchQuery
from .base import SourceAdapter
from .http_base import GLOBAL_KILL_SWITCH_ENV

CONFIRM_ENV = "FF_SOURCING_SELFCHECK_CONFIRM"
ADAPTER_IDS = ("alibaba", "alibaba_openapi", "aliexpress", "made_in_china", "source_1688")
_TRUTHY = {"1", "true", "yes", "on"}
_SECRET_HINTS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "TRACKING")

# field -> populated?  (a field the source cannot provide is reported "missing", never invented)
CHECKS: dict[str, Callable[[ListingDetail], bool]] = {
    "title": lambda x: bool(x.title.strip()),
    "price": lambda x: x.price.min.amount > 0 and x.price.max.amount >= x.price.min.amount,
    "currency": lambda x: len(x.price.min.currency) == 3,
    "moq": lambda x: x.moq is not None,
    "unit": lambda x: bool(x.unit),
    "supplier_id": lambda x: bool(x.supplier.id) and "unknown-" not in x.supplier.id,
    "supplier_name": lambda x: bool(x.supplier.name) and x.supplier.name != "Unknown supplier",
    "url": lambda x: bool(x.source_url),
    "images": lambda x: len(x.images) > 0,
    "country": lambda x: bool(x.supplier.location.country_code),
    "city": lambda x: bool(x.supplier.location.city),
    "verified": lambda x: x.supplier.verified,
}
REQUIRED = ("title", "price", "currency", "moq", "supplier_id", "supplier_name", "url", "images")


def missing_fields(listing: ListingDetail, fields: tuple[str, ...] = REQUIRED) -> set[str]:
    return {f for f in fields if not CHECKS[f](listing)}


def coverage(listings: list[ListingDetail]) -> dict[str, int]:
    return {name: sum(1 for it in listings if fn(it)) for name, fn in CHECKS.items()}


def make_adapter(adapter_id: str, settings: Settings, env: Mapping[str, str], client: httpx.AsyncClient | None) -> SourceAdapter:
    if adapter_id == "alibaba":
        from .alibaba import AlibabaAdapter
        return AlibabaAdapter(settings, client=client)
    if adapter_id == "alibaba_openapi":
        from .alibaba_openapi import AlibabaOpenApiAdapter
        return AlibabaOpenApiAdapter(client=client, env=env)
    if adapter_id == "aliexpress":
        from .aliexpress import AliExpressAdapter
        return AliExpressAdapter(settings, client=client)
    if adapter_id == "made_in_china":
        from .made_in_china import MadeInChinaAdapter
        return MadeInChinaAdapter(settings, client=client)
    if adapter_id == "source_1688":
        from .source_1688 import Source1688Adapter
        return Source1688Adapter(settings, client=client)
    raise ValueError(f"unknown adapter {adapter_id!r}; choose one of {', '.join(ADAPTER_IDS)}")


def _scrub(text: str, env: Mapping[str, str]) -> str:
    for k, v in env.items():
        if v and len(v) >= 4 and any(h in k.upper() for h in _SECRET_HINTS):
            text = text.replace(v, "***")
    return text


def format_report(adapter_id: str, listings: list[ListingDetail]) -> str:
    n = len(listings)
    lines = [f"selfcheck {adapter_id}: {n} listing(s) normalised (1 search call, nothing stored)"]
    if not n:
        lines.append("  no listings: check credentials, query, or the response mapping (VERIFY AGAINST OFFICIAL DOCS)")
        return "\n".join(lines)
    cov = coverage(listings)
    for name in CHECKS:
        tag = "OK     " if cov[name] == n else ("PARTIAL" if cov[name] else "MISSING")
        lines.append(f"  {tag} {name:<14}{cov[name]}/{n}")
    bad = [f for f in REQUIRED if cov[f] < n]
    lines.append("required fields not fully populated: " + (", ".join(bad) if bad else "none"))
    return "\n".join(lines)


async def run_selfcheck(
    adapter_id: str,
    query: str = "led light",
    *,
    settings: Settings | None = None,
    env: Mapping[str, str] | None = None,
    client: httpx.AsyncClient | None = None,
    out: Callable[[str], Any] = print,
) -> int:
    """Return a process exit code (0 ok, 2 refused, 1 call failed)."""
    env = os.environ if env is None else env
    if adapter_id not in ADAPTER_IDS:
        out(f"unknown adapter {adapter_id!r}; choose one of {', '.join(ADAPTER_IDS)}")
        return 2
    if env.get(CONFIRM_ENV, "").strip().lower() not in _TRUTHY:
        out(f"refused: set {CONFIRM_ENV}=1 to confirm you want ONE real upstream call")
        return 2
    switches = (GLOBAL_KILL_SWITCH_ENV, f"FF_SOURCING_{adapter_id.upper()}_DISABLED")
    if any(env.get(n, "").strip().lower() in _TRUTHY for n in switches):
        out("refused: kill switch is on; no request sent")
        return 2
    adapter = make_adapter(adapter_id, settings or Settings(), env, client)
    if not adapter.configured():
        out(f"refused: {adapter_id} is not configured (credentials/config come from env only)")
        return 2
    q = SearchQuery(q=query, keywords_en=query.split(), limit=5)
    try:
        listings = await adapter.search(q)
    except Exception as exc:  # message is already URL-redacted by the adapters; scrub again
        out(f"call failed: {type(exc).__name__}: {_scrub(str(exc), env)[:200]}")
        return 1
    out(format_report(adapter_id, listings))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    return asyncio.run(run_selfcheck(args[0], " ".join(args[1:]) or "led light"))


if __name__ == "__main__":
    raise SystemExit(main())
