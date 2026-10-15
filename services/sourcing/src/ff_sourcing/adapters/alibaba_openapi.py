"""Alibaba.com Open Platform product search -> Listing contract.

*** UNVERIFIED against the live API. *** Endpoint, method name, signing details and response
shape below follow the public shape of Alibaba's TOP-style Open Platform
(`/sync?method=...&app_key&timestamp&sign_method=sha256&sign`, `*_response` envelope) as best
known, not a tested integration. Before enabling: check the current docs at
https://open.alibaba.com, confirm buyer-side search is available to the account, and replace
`tests/fixtures/alibaba_openapi_search.json` (a hand-authored SYNTHETIC fixture, NOT a recording)
with a REAL recorded response. Nothing here has been verified against Alibaba's servers.

Credentials (env only): FF_SOURCING_ALIBABA_APP_KEY, FF_SOURCING_ALIBABA_APP_SECRET,
FF_SOURCING_ALIBABA_ACCESS_TOKEN. Kill switch: FF_SOURCING_ALIBABA_OPENAPI_DISABLED.
Terms: use only within the Open Platform agreement; no scraping; honour quotas.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import httpx

from ..domain.models import SearchQuery
from .http_base import hmac_sign
from .http_provider import HttpProviderAdapter, ProviderConfig

APP_KEY_ENV = "FF_SOURCING_ALIBABA_APP_KEY"
APP_SECRET_ENV = "FF_SOURCING_ALIBABA_APP_SECRET"
ACCESS_TOKEN_ENV = "FF_SOURCING_ALIBABA_ACCESS_TOKEN"
METHOD = "alibaba.icbu.product.search"  # UNVERIFIED method name

ALIBABA_OPENAPI_CONFIG = ProviderConfig(
    id="alibaba_openapi",
    name="Alibaba.com Open Platform (UNVERIFIED skeleton)",
    base_url="https://openapi-api.alibaba.com",
    search_path="/sync",
    mode="official_api",
    api_key_env=APP_KEY_ENV,
    kill_switch_env="FF_SOURCING_ALIBABA_OPENAPI_DISABLED",
    results_path="alibaba_icbu_product_search_response.products.product",
    field_map={
        "id": "product_id",
        "title": "subject",
        "price_range": "price",  # e.g. "US $12.50-15.00"
        "currency": "currency",
        "supplier_id": "supplier.id",
        "supplier_name": "supplier.name",
        "country": "supplier.country",
        "city": "supplier.city",
        "url": "detail_url",
        "images": "images[].url",
        "moq": "min_order_quantity",
        "unit": "unit",
        "verified": "supplier.is_verified",
    },
    tos_note="Alibaba Open Platform agreement; official API only; UNVERIFIED mapping.",
)


class AlibabaOpenApiAdapter(HttpProviderAdapter):
    volatile_params = frozenset({"timestamp", "sign"})

    def __init__(
        self,
        config: ProviderConfig | None = None,
        client: httpx.AsyncClient | None = None,
        env: Mapping[str, str] | None = None,
        **kw: Any,
    ):
        super().__init__(config or ALIBABA_OPENAPI_CONFIG, client=client, env=env, **kw)

    def configured(self) -> bool:
        return all(self._env.get(n) for n in (APP_KEY_ENV, APP_SECRET_ENV, ACCESS_TOKEN_ENV))

    def build_headers(self) -> dict[str, str]:
        return {"User-Agent": self.config.user_agent, "Accept": "application/json"}

    def build_params(self, query: SearchQuery) -> dict[str, Any]:
        p: dict[str, Any] = {
            "method": METHOD,
            "app_key": self._env.get(APP_KEY_ENV, ""),
            "access_token": self._env.get(ACCESS_TOKEN_ENV, ""),
            "sign_method": "sha256",
            "timestamp": str(int(time.time() * 1000)),
            "keywords": " ".join(query.keywords_en) or query.q,
            "page_size": min(query.limit, 50),
        }
        p["sign"] = hmac_sign(p, self._env.get(APP_SECRET_ENV, ""))
        return p
