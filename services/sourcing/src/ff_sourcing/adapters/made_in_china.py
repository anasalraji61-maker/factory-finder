"""Made-in-China.com.

There is no public search API. Compliance options, in order of preference:
  1. a licensed partner/data feed (FF_SOURCING_MIC_API_BASE + FF_SOURCING_MIC_API_KEY);
  2. public pages ONLY if FF_SOURCING_MIC_ALLOW_PUBLIC_PAGES=true, after the site's Terms of Use
     have been reviewed by a human, and only for paths robots.txt allows (enforced by RobotsGuard).
Never bypass CAPTCHAs, logins or paywalls (a 401/403/429 aborts the call).
"""

from __future__ import annotations

from typing import Any

from ..domain.models import ListingDetail, SearchQuery
from ._norm import build_listing
from .http_base import ApiSourceAdapter, HttpRequestSpec


class MadeInChinaAdapter(ApiSourceAdapter):
    id = "made_in_china"
    name = "Made-in-China.com (licensed feed)"
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
        return list(payload.get("items", []))

    def normalize_item(self, raw: dict[str, Any]) -> ListingDetail:
        return build_listing(
            source=self.id,
            native_id=str(raw["id"]),
            title=raw.get("title", ""),
            price_min=raw.get("price_min", 0),
            price_max=raw.get("price_max"),
            currency=raw.get("currency", "USD"),
            supplier_native_id=str(raw.get("company_id", "")),
            supplier_name=raw.get("company", ""),
            city=raw.get("city"),
            url=raw.get("url"),
            images=raw.get("images", []),
            moq=raw.get("moq"),
            unit=raw.get("unit"),
            verified=bool(raw.get("audited")),
        )
