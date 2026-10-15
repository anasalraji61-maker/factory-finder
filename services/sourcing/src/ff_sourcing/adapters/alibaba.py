"""Alibaba.com via the official Open Platform API (https://open.alibaba.com).

Compliance: official API only, signed requests, app key/secret from env
(FF_SOURCING_ALIBABA_APP_KEY / _APP_SECRET). No page scraping. Verify endpoint names against the
current Open Platform docs before enabling: this is a request/normalization skeleton.
"""

from __future__ import annotations

import time
from typing import Any

from ..domain.models import ListingDetail, SearchQuery
from ._norm import build_listing, resolve_price, to_moq
from .http_base import ApiSourceAdapter, HttpRequestSpec, hmac_sign


class AlibabaAdapter(ApiSourceAdapter):
    id = "alibaba"
    name = "Alibaba.com (Open Platform API)"
    compliance = (
        "Official Open Platform API; signed requests; <=1 req/3s/host; cached; off by default."
    )

    def configured(self) -> bool:
        return bool(self.settings.alibaba_app_key and self.settings.alibaba_app_secret)

    def build_search_request(self, query: SearchQuery) -> HttpRequestSpec:
        params: dict[str, Any] = {
            "app_key": self.settings.alibaba_app_key,
            "timestamp": str(int(time.time() * 1000)),
            "sign_method": "sha256",
            "keyword": " ".join(query.keywords_en) or query.q,
            "page_size": min(query.limit, 50),
        }
        params["sign"] = hmac_sign(params, self.settings.alibaba_app_secret)
        return HttpRequestSpec(
            url=f"{self.settings.alibaba_api_base}/products/search", params=params
        )

    def parse_search_response(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        return list(payload.get("result", {}).get("products", []))

    def normalize_item(self, raw: dict[str, Any]) -> ListingDetail | None:
        if raw.get("id") in (None, ""):
            return None
        price = raw.get("price")
        if not isinstance(price, dict) or resolve_price(
            lo=price.get("min"), default_currency="USD"
        ) is None:
            return None
        return build_listing(
            source=self.id,
            native_id=str(raw["id"]),
            title=raw.get("subject", ""),
            price_min=price.get("min", 0),
            price_max=price.get("max", price.get("min", 0)),
            currency=price.get("currency", "USD"),
            supplier_native_id=str(raw.get("seller_id", "")),
            supplier_name=raw.get("seller_name", ""),
            country=raw.get("country", "CN"),
            city=raw.get("city"),
            url=raw.get("detail_url"),
            images=raw.get("images", []),
            moq=to_moq(raw.get("moq")),
            unit=raw.get("unit"),
            verified=bool(raw.get("verified_supplier")),
        )
