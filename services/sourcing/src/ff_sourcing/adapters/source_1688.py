"""1688.com via the 1688 Open Platform (https://open.1688.com).

*** UNVERIFIED against the live API. *** The endpoint path, signature recipe and the
`result.toReturn[]` response shape below are an assumption about the 1688 Open Platform, NOT a
tested integration. `tests/fixtures/s1688_search.json` is a hand-authored SYNTHETIC fixture, not a
recorded response. Before enabling: confirm the current docs and account entitlement, then replace
the fixture with a real recording.

Compliance: official Open Platform API, app key/secret from env (FF_SOURCING_S1688_*). 1688 is a
domestic-China wholesale site: prices default to CNY and suppliers may not export; the trust service and
landed-cost engine must treat results accordingly. No page scraping.

EXPECTED OFFICIAL CONTRACT -- *** VERIFY AGAINST OFFICIAL DOCS *** (nothing below is confirmed)
  Docs link: <PLACEHOLDER: official 1688 Open Platform alibaba.product.search page>
  Request : GET {FF_SOURCING_S1688_API_BASE}/param2/1/com.alibaba.product/alibaba.product.search/{app_key}
            params: keywords (Chinese), pageSize(<=50), _aop_signature (upper-hex HMAC-SHA1 over
            the URL path + sorted k+v with the app secret)
  Response: result.toReturn[]
  Item fields read: offerId, subject, price (text) | priceMin/priceMax, memberId, companyName, city,
            detailUrl, imageUrl, images[], minOrderQuantity, unit, tpYear
  Likely also needs an access_token for most 1688 APIs -- not sent today; confirm.
  Owner check: `python -m ff_sourcing.adapters.selfcheck source_1688`.
"""

from __future__ import annotations

from typing import Any

from ..domain.models import ListingDetail, SearchQuery
from ._norm import (
    build_listing,
    clean_unit,
    dig,
    image_list,
    resolve_price,
    to_moq,
    truthy,
)
from .http_base import ApiSourceAdapter, HttpRequestSpec, hmac_sign


class Source1688Adapter(ApiSourceAdapter):
    id = "source_1688"
    name = "1688.com (Open Platform API, UNVERIFIED skeleton)"
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
        items = dig(payload, "result", "toReturn")
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    def normalize_item(self, raw: dict[str, Any]) -> ListingDetail | None:
        native_id = raw.get("offerId")
        if native_id in (None, ""):
            return None
        price = resolve_price(
            text=raw.get("price"),
            lo=raw.get("priceMin"),
            hi=raw.get("priceMax"),
            default_currency="CNY",  # domestic wholesale: CNY unless the text says otherwise
            country="CN",
        )
        if price is None:
            return None
        images = image_list(raw.get("imageUrl")) + image_list(raw.get("images"))
        return build_listing(
            source=self.id,
            native_id=str(native_id),
            title=raw.get("subject") or "",
            price_min=price.lo,
            price_max=price.hi,
            currency=price.currency or "CNY",
            supplier_native_id=raw.get("memberId"),
            supplier_name=raw.get("companyName") or "",
            city=raw.get("city"),
            url=raw.get("detailUrl"),
            images=images,
            moq=to_moq(raw.get("minOrderQuantity")) or price.moq,
            unit=clean_unit(raw.get("unit")) or price.unit,
            verified=to_moq(raw.get("tpYear")) is not None or truthy(raw.get("tpYear")),  # years as a TrustPass member
        )
