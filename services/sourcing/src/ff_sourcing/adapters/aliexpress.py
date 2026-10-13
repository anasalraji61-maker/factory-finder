"""AliExpress via the Affiliate API (aliexpress.affiliate.product.query).

Compliance: official affiliate API with app key/secret + tracking id from env
(FF_SOURCING_ALIEXPRESS_*). Retail marketplace: items are consumer-scale, MOQ defaults to 1.
"""

from __future__ import annotations

import time
from typing import Any

from ..domain.models import ListingDetail, SearchQuery
from ._norm import build_listing
from .http_base import ApiSourceAdapter, HttpRequestSpec, hmac_sign


class AliExpressAdapter(ApiSourceAdapter):
    id = "aliexpress"
    name = "AliExpress (Affiliate API)"
    compliance = "Official Affiliate API; signed; <=1 req/3s/host; cached; off by default."

    def configured(self) -> bool:
        s = self.settings
        return bool(s.aliexpress_app_key and s.aliexpress_app_secret and s.aliexpress_tracking_id)

    def build_search_request(self, query: SearchQuery) -> HttpRequestSpec:
        s = self.settings
        params: dict[str, Any] = {
            "method": "aliexpress.affiliate.product.query",
            "app_key": s.aliexpress_app_key,
            "timestamp": str(int(time.time() * 1000)),
            "sign_method": "sha256",
            "keywords": " ".join(query.keywords_en) or query.q,
            "tracking_id": s.aliexpress_tracking_id,
            "page_size": min(query.limit, 50),
            "target_currency": "USD",
        }
        params["sign"] = hmac_sign(params, s.aliexpress_app_secret)
        return HttpRequestSpec(url=s.aliexpress_api_base, params=params)

    def parse_search_response(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        resp = payload.get("aliexpress_affiliate_product_query_response", {}).get("resp_result", {})
        return list(resp.get("result", {}).get("products", {}).get("product", []))

    def normalize_item(self, raw: dict[str, Any]) -> ListingDetail:
        return build_listing(
            source=self.id,
            native_id=str(raw["product_id"]),
            title=raw.get("product_title", ""),
            price_min=raw.get("target_sale_price", 0),
            price_max=raw.get("target_original_price"),
            currency=raw.get("target_sale_price_currency", "USD"),
            supplier_native_id=str(raw.get("shop_id", "")),
            supplier_name=raw.get("shop_url", "AliExpress shop"),
            url=raw.get("promotion_link") or raw.get("product_detail_url"),
            images=[raw["product_main_image_url"]] if raw.get("product_main_image_url") else [],
            moq=1,
            unit="piece",
        )
