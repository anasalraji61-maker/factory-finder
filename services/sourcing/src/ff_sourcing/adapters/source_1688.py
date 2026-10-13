"""1688.com via the 1688 Open Platform (https://open.1688.com).

Compliance: official Open Platform API, app key/secret from env (FF_SOURCING_S1688_*). 1688 is a
domestic-China wholesale site: prices are CNY and suppliers may not export; the trust service and
landed-cost engine must treat results accordingly. No page scraping.
"""

from __future__ import annotations

from typing import Any

from ..domain.models import ListingDetail, SearchQuery
from ._norm import build_listing
from .http_base import ApiSourceAdapter, HttpRequestSpec, hmac_sign


class Source1688Adapter(ApiSourceAdapter):
    id = "source_1688"
    name = "1688.com (Open Platform API)"
    compliance = "Official Open Platform API; signed; <=1 req/3s/host; cached; off by default."

    def configured(self) -> bool:
        return bool(self.settings.s1688_app_key and self.settings.s1688_app_secret)

    def build_search_request(self, query: SearchQuery) -> HttpRequestSpec:
        s = self.settings
        path = f"param2/1/com.alibaba.product/alibaba.product.search/{s.s1688_app_key}"
        params: dict[str, Any] = {
            "keywords": query.q or " ".join(query.keywords_en),  # 1688 expects Chinese keywords
            "pageSize": min(query.limit, 50),
        }
        params["_aop_signature"] = hmac_sign(params, s.s1688_app_secret, algo="sha1", prefix=path)
        return HttpRequestSpec(url=f"{s.s1688_api_base}/{path}", params=params)

    def parse_search_response(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return list(payload.get("result", {}).get("toReturn", []))

    def normalize_item(self, raw: dict[str, Any]) -> ListingDetail:
        return build_listing(
            source=self.id,
            native_id=str(raw["offerId"]),
            title=raw.get("subject", ""),
            price_min=raw.get("priceMin", raw.get("price", 0)),
            price_max=raw.get("priceMax", raw.get("price")),
            currency="CNY",
            supplier_native_id=str(raw.get("memberId", "")),
            supplier_name=raw.get("companyName", ""),
            city=raw.get("city"),
            url=raw.get("detailUrl"),
            images=[raw["imageUrl"]] if raw.get("imageUrl") else [],
            moq=raw.get("minOrderQuantity"),
            unit=raw.get("unit"),
            verified=bool(raw.get("tpYear")),
        )
