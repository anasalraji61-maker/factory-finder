"""AliExpress via the Affiliate API (aliexpress.affiliate.product.query).

*** UNVERIFIED against the live API. *** Method name, signing recipe and the
`aliexpress_affiliate_product_query_response.resp_result.result.products.product[]` envelope are
an assumption from the public affiliate-API naming, NOT a tested integration.
`tests/fixtures/aliexpress_affiliate_query.json` is a hand-authored SYNTHETIC fixture. Before
enabling: check the current AliExpress Open Platform docs and replace it with a real recording.

Compliance: official affiliate API with app key/secret + tracking id from env
(FF_SOURCING_ALIEXPRESS_*). Retail marketplace: items are consumer-scale, MOQ defaults to 1.
"""

from __future__ import annotations

import time
from typing import Any

from ..domain.models import ListingDetail, SearchQuery
from ._norm import (
    build_listing,
    dig,
    image_list,
    read_price,
    resolve_price,
    safe_http_url,
)
from .http_base import ApiSourceAdapter, HttpRequestSpec, hmac_sign


class AliExpressAdapter(ApiSourceAdapter):
    id = "aliexpress"
    name = "AliExpress (Affiliate API, UNVERIFIED skeleton)"
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
        items = dig(
            payload,
            "aliexpress_affiliate_product_query_response",
            "resp_result",
            "result",
            "products",
            "product",
        )
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    def normalize_item(self, raw: dict[str, Any]) -> ListingDetail | None:
        native_id = raw.get("product_id")
        if native_id in (None, ""):
            return None
        price = resolve_price(
            lo=raw.get("target_sale_price"),
            hi=raw.get("target_original_price"),
            currency=raw.get("target_sale_price_currency"),
            default_currency="USD",  # request asks target_currency=USD
        )
        if price is None:
            return None
        orig = read_price(raw.get("target_original_price"))
        hi = orig.hi if orig and orig.hi >= price.lo else price.hi
        shop_id = raw.get("shop_id")
        images = image_list(raw.get("product_main_image_url")) + image_list(
            raw.get("product_small_image_urls")
        )
        return build_listing(
            source=self.id,
            native_id=str(native_id),
            title=raw.get("product_title") or "",
            price_min=price.lo,
            price_max=hi,
            currency=price.currency or "USD",
            supplier_native_id=shop_id,
            supplier_name=f"AliExpress shop {shop_id}" if shop_id not in (None, "") else "",
            url=safe_http_url(raw.get("promotion_link")) or raw.get("product_detail_url"),
            images=images,
            moq=1,
            unit="piece",
        )
