"""Made-in-China.com.

*** UNVERIFIED. *** There is no public search API known to us; the `{"items": [...]}` feed shape and
field names below are an ASSUMED licensed-feed contract, not a documented Made-in-China format.
`tests/fixtures/mic_feed_search.json` is a hand-authored SYNTHETIC fixture. Replace it with the
real partner feed's sample once a license exists.

Compliance options, in order of preference:
  1. a licensed partner/data feed (FF_SOURCING_MIC_API_BASE + FF_SOURCING_MIC_API_KEY);
  2. public pages ONLY if FF_SOURCING_MIC_ALLOW_PUBLIC_PAGES=true, after the site's Terms of Use
     have been reviewed by a human, and only for paths robots.txt allows (enforced by RobotsGuard).
Never bypass CAPTCHAs, logins or paywalls (a 401/403/429 aborts the call).

EXPECTED CONTRACT -- *** VERIFY AGAINST THE PARTNER'S OFFICIAL DOCS *** (assumed, no public API known)
  Docs link: <PLACEHOLDER: licensed partner feed specification, if/when a license exists>
  Request : GET {FF_SOURCING_MIC_API_BASE}/search?q=<keywords>&limit=<=50
            header Authorization: Bearer <FF_SOURCING_MIC_API_KEY> (public-page mode: robots-checked)
  Response: {"items": [ {...} ]}
  Item fields read: id, title, price (text) | price_min/price_max, currency, company_id, company,
            city, url, images (strings or [{"url"}]), moq, unit, audited
  Owner check: `python -m ff_sourcing.adapters.selfcheck made_in_china` (public-page mode also
            makes one robots.txt request).
"""

from __future__ import annotations

from typing import Any

from ..domain.models import ListingDetail, SearchQuery
from ._norm import (
    build_listing,
    clean_unit,
    image_list,
    resolve_price,
    to_moq,
    truthy,
)
from .http_base import ApiSourceAdapter, HttpRequestSpec


class MadeInChinaAdapter(ApiSourceAdapter):
    id = "made_in_china"
    name = "Made-in-China.com (licensed feed, UNVERIFIED shape)"
    mode = "licensed_feed"
    compliance = "Licensed feed or robots-checked public pages only; <=1 req/3s/host; cached; off by default."

    def configured(self) -> bool:
        s = self.settings
        return bool(s.mic_api_base and (s.mic_api_key or s.mic_allow_public_pages))

    def build_search_request(self, query: SearchQuery) -> HttpRequestSpec:
        s = self.settings
        headers = {"Authorization": f"Bearer {s.mic_api_key}"} if s.mic_api_key else {}
        return HttpRequestSpec(
            url=f"{s.mic_api_base.rstrip('/')}/search",
            params={"q": " ".join(query.keywords_en) or query.q, "limit": min(query.limit, 50)},
            headers=headers,
            kind="api" if s.mic_api_key else "page",
        )

    def parse_search_response(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        items = payload.get("items")
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    def normalize_item(self, raw: dict[str, Any]) -> ListingDetail | None:
        native_id = raw.get("id")
        if native_id in (None, ""):
            return None
        price = resolve_price(
            text=raw.get("price"),
            lo=raw.get("price_min"),
            hi=raw.get("price_max"),
            currency=raw.get("currency"),
            default_currency="USD",
        )
        if price is None:
            return None
        return build_listing(
            source=self.id,
            native_id=str(native_id),
            title=raw.get("title") or "",
            price_min=price.lo,
            price_max=price.hi,
            currency=price.currency or "USD",
            supplier_native_id=raw.get("company_id"),
            supplier_name=raw.get("company") or "",
            city=raw.get("city"),
            url=raw.get("url"),
            images=image_list(raw.get("images")),
            moq=to_moq(raw.get("moq")) or price.moq,
            unit=clean_unit(raw.get("unit")) or price.unit,
            verified=truthy(raw.get("audited")),
        )
