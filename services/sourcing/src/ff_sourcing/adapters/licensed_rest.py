"""Generic LICENSED REST provider adapter driven by a declarative JSON mapping file.

The owner plugs in any licensed/official supplier-data API without code: endpoint templates, auth
(header | query | bearer, key read from an env var NAMED in the file), pagination, field mapping,
currency/unit normalization, image host allowlist, timeouts and cache. The key itself never lives in
the repo or the mapping. Compliance (CLAUDE.md rule 6) is inherited from HttpProviderAdapter:
>= 3 s/host throttle floor, cache, kill switch (global + per-provider), honest User-Agent,
401/403/429 => SourceBlocked (no retry/bypass). Official/licensed API only: no page scraping.
On any failure the SourcingService degrades to the mock adapter with a visible warning.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..domain.models import ListingDetail, SearchQuery
from ..domain.quality import (
    dedupe_listings,
    detect_currency,
    normalize_currency_code,
    price_is_sane,
)
from ._norm import build_listing, dec
from .http_provider import (
    MIN_INTERVAL_FLOOR_S,
    HttpProviderAdapter,
    ProviderConfig,
    get_path,
    parse_price_range,
)

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
PLACEHOLDERS = {"keywords", "q", "limit", "page", "offset", "cursor", "country", "category"}
TARGETS = {
    "id", "title", "price_min", "price_max", "price_range", "currency", "supplier_id",
    "supplier_name", "country", "city", "url", "images", "moq", "unit", "verified",
    "description", "category",
}
REQUIRED_TARGETS = {"id", "title", "supplier_name"}
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_SECRET_LIKE = re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd)=\S{8,}")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Auth(_Strict):
    style: Literal["header", "query", "bearer", "none"] = "bearer"
    key_env: str = ""  # NAME of the env var holding the key
    name: str = ""  # header name (style=header) or query parameter (style=query)
    prefix: str = ""  # optional value prefix for style=header

    @model_validator(mode="after")
    def _check(self) -> Auth:
        if self.style == "none":
            return self
        if not _ENV_NAME.match(self.key_env):
            raise ValueError("auth.key_env must be an ENV VAR NAME like FF_SOURCING_X_API_KEY, not a key")
        if self.style in ("header", "query") and not self.name:
            raise ValueError(f"auth.name is required for style={self.style}")
        return self


class RequestSpec(_Strict):
    method: Literal["GET"] = "GET"
    path: str
    query: dict[str, str] = {}
    headers: dict[str, str] = {}


class Pagination(_Strict):
    style: Literal["none", "page", "offset", "cursor"] = "none"
    page_param: str = "page"
    size_param: str = ""
    offset_param: str = "offset"
    cursor_param: str = "cursor"
    next_cursor_path: str = ""
    page_size: int = Field(default=50, ge=1, le=200)
    first_page: int = Field(default=1, ge=0, le=1)
    max_pages: int = Field(default=1, ge=1, le=10)


class Currency(_Strict):
    allowed: list[str] = []  # empty = any; otherwise items in other currencies are dropped
    aliases: dict[str, str] = {}  # e.g. {"RMB": "CNY", "¥": "CNY"}
    detect_from_price_text: bool = True


class Units(_Strict):
    aliases: dict[str, str] = {}  # {"pcs": "piece", "tonne": "ton"}
    price_scale: str = "1"  # multiply raw prices (e.g. "0.01" when the API returns minor units)


class Images(_Strict):
    allowed_hosts: list[str] = []  # exact host or ".suffix"; empty list = NO images are kept
    https_only: bool = True
    max: int = Field(default=8, ge=0, le=30)


class Limits(_Strict):
    timeout_s: float = Field(default=8.0, gt=0, le=60)
    min_interval_s: float = Field(default=MIN_INTERVAL_FLOOR_S)  # clamped UP to the 3 s floor
    cache_ttl_s: float = Field(default=300.0, ge=0)


class Quality(_Strict):
    min_price: Decimal = Decimal("0.0001")
    max_price: Decimal = Decimal("100000000")
    max_ratio: Decimal = Decimal("1000")
    dedupe_threshold: float = Field(default=0.9, ge=0.5, le=1.0)


class MappingSpec(_Strict):
    schema_version: int = SCHEMA_VERSION
    id: str
    name: str
    example: bool = False  # EXAMPLE files must say so; refused unless allow_example
    description: str = ""
    mode: Literal["licensed_feed", "official_api"] = "licensed_feed"
    tos_note: str  # REQUIRED: which agreement/licence covers this data use
    robots_note: str  # REQUIRED: why robots.txt is not applicable (API) or how it was checked
    base_url: str
    kill_switch_env: str = ""
    auth: Auth
    request: RequestSpec
    pagination: Pagination = Pagination()
    items_path: str
    fields: dict[str, str]
    defaults: dict[str, str] = {"currency": "USD", "country": "CN"}
    currency: Currency = Currency()
    units: Units = Units()
    images: Images = Images()
    limits: Limits = Limits()
    quality: Quality = Quality()

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,31}", v) or v in {"mock", "native"}:
            raise ValueError("id must be lowercase [a-z0-9_], 3-32 chars, not mock/native")
        return v

    @field_validator("base_url")
    @classmethod
    def _base(cls, v: str) -> str:
        p = urlsplit(v)
        if p.scheme != "https" or not p.hostname or p.username or p.password or p.query:
            raise ValueError("base_url must be https://host[/prefix] without credentials or query")
        return v.rstrip("/")

    @field_validator("tos_note", "robots_note")
    @classmethod
    def _notes(cls, v: str) -> str:
        if len(v.strip()) < 10:
            raise ValueError("must be a real sentence (>= 10 chars)")
        return v

    @field_validator("kill_switch_env")
    @classmethod
    def _ks(cls, v: str) -> str:
        if v and not _ENV_NAME.match(v):
            raise ValueError("kill_switch_env must be an env var name")
        return v

    @field_validator("defaults")
    @classmethod
    def _defaults(cls, v: dict[str, str]) -> dict[str, str]:
        bad = set(v) - {"currency", "country", "unit"}
        if bad:
            raise ValueError(f"unknown defaults: {sorted(bad)}")
        return v

    @model_validator(mode="after")
    def _cross(self) -> MappingSpec:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {self.schema_version}")
        if not self.request.path.startswith("/"):
            raise ValueError("request.path must start with '/'")
        unknown = set(self.fields) - TARGETS
        if unknown:
            raise ValueError(f"unknown field targets: {sorted(unknown)}")
        missing = REQUIRED_TARGETS - set(self.fields)
        if missing:
            raise ValueError(f"fields must map: {sorted(missing)}")
        if not ({"price_min", "price_range"} & set(self.fields)):
            raise ValueError("fields must map price_min or price_range")
        templates = [self.request.path, *self.request.query.values(), *self.request.headers.values()]
        for t in templates:
            for ph in _PLACEHOLDER.findall(t):
                if ph not in PLACEHOLDERS:
                    raise ValueError(f"unknown placeholder {{{ph}}} (allowed: {sorted(PLACEHOLDERS)})")
            if _SECRET_LIKE.search(t):
                raise ValueError("a credential appears to be written into a template; use auth.key_env")
        for k in self.request.headers:
            if k.lower() in {"authorization", "x-api-key", "api-key", "cookie", "user-agent"}:
                raise ValueError(f"header {k!r} is managed by auth/User-Agent settings; do not set it here")
        if self.auth.style == "query" and self.auth.name in self.request.query:
            raise ValueError("auth.name must not also appear in request.query")
        pg = self.pagination
        if pg.style == "cursor" and not pg.next_cursor_path:
            raise ValueError("pagination.next_cursor_path is required for style=cursor")
        try:
            if Decimal(self.units.price_scale) <= 0:
                raise ValueError
        except Exception as exc:
            raise ValueError("units.price_scale must be a positive decimal string") from exc
        if not re.fullmatch(r"[A-Z]{3}", self.defaults.get("currency", "")):
            raise ValueError("defaults.currency must be an ISO 4217 code")
        if self.currency.allowed and self.defaults["currency"] not in self.currency.allowed:
            raise ValueError("defaults.currency must be in currency.allowed")
        return self


def warnings_for(spec: MappingSpec) -> list[str]:
    """Non-fatal advice shown by the validator CLI."""
    w: list[str] = []
    if spec.limits.min_interval_s < MIN_INTERVAL_FLOOR_S:
        w.append(f"limits.min_interval_s < {MIN_INTERVAL_FLOOR_S:g}: will be clamped up to the floor")
    if spec.pagination.max_pages > 1:
        w.append("max_pages > 1 needs >= 3 s per extra page: raise FF_SOURCING_ADAPTER_TIMEOUT_S accordingly")
    if not spec.images.allowed_hosts:
        w.append("images.allowed_hosts is empty: no image URLs will be kept")
    if spec.auth.style == "none":
        w.append("auth.style=none: only use for keyless official endpoints")
    if "currency" not in spec.fields and not spec.currency.detect_from_price_text:
        w.append("no currency mapping or detection: every price is assumed " + spec.defaults["currency"])
    if spec.example:
        w.append("mapping is flagged example=true: it will not load unless examples are allowed")
    return w


def load_mapping(source: str | Path | Mapping[str, Any]) -> MappingSpec:
    """Load from a path or an already-parsed dict. Raises ValueError with readable messages."""
    try:
        data = json.loads(Path(source).read_text("utf-8")) if isinstance(source, str | Path) else dict(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read mapping: {exc}") from exc
    data.pop("_comment", None)
    try:
        return MappingSpec.model_validate(data)
    except ValidationError as exc:
        msgs = [f"{'.'.join(map(str, e['loc'])) or '<root>'}: {e['msg']}" for e in exc.errors()]
        raise ValueError("; ".join(msgs)) from exc


def fill(template: str, values: Mapping[str, Any], *, quote_value: bool) -> str:
    def sub(m: re.Match[str]) -> str:
        v = str(values.get(m.group(1), ""))
        return quote(v, safe="") if quote_value else v

    return _PLACEHOLDER.sub(sub, template)


def host_allowed(url: str, allowed: list[str], https_only: bool) -> bool:
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if not host or p.scheme not in ("https", "http") or (https_only and p.scheme != "https"):
        return False
    return any(host == a.lower() or (a.startswith(".") and host.endswith(a.lower())) for a in allowed)


def _provider_config(spec: MappingSpec) -> ProviderConfig:
    return ProviderConfig(
        id=spec.id, name=spec.name, base_url=spec.base_url, search_path=spec.request.path,
        method=spec.request.method, api_key_env=spec.auth.key_env if spec.auth.style != "none" else "",
        kill_switch_env=spec.kill_switch_env, results_path=spec.items_path, field_map=spec.fields,
        currency_default=spec.defaults["currency"], country_default=spec.defaults.get("country", "CN"),
        mode=spec.mode, min_interval_s=spec.limits.min_interval_s, cache_ttl_s=spec.limits.cache_ttl_s,
        timeout_s=spec.limits.timeout_s,
        tos_note=f"{spec.tos_note} Robots: {spec.robots_note}",
    )


class LicensedRestAdapter(HttpProviderAdapter):
    def __init__(
        self,
        spec: MappingSpec,
        client: httpx.AsyncClient | None = None,
        env: Mapping[str, str] | None = None,
        **kw: Any,
    ):
        super().__init__(_provider_config(spec), client=client, env=env, **kw)
        self.spec = spec
        if spec.auth.style == "query":
            self.volatile_params = frozenset({spec.auth.name})  # key never part of cache keys

    # ---- request ----------------------------------------------------------
    def _values(self, query: SearchQuery, page: int, cursor: str) -> dict[str, Any]:
        pg = self.spec.pagination
        size = min(query.limit, pg.page_size)
        kw = " ".join(query.keywords_en) or query.q
        return {
            "keywords": kw, "q": query.q, "limit": size, "page": page,
            "offset": (page - pg.first_page) * size, "cursor": cursor,
            "country": query.origin_country or "", "category": query.category or "",
        }

    def build_params(self, query: SearchQuery, page: int = 1, cursor: str = "") -> dict[str, Any]:
        s, pg = self.spec, self.spec.pagination
        vals = self._values(query, page, cursor)
        params = {k: fill(v, vals, quote_value=False) for k, v in s.request.query.items()}
        if pg.style == "page":
            params[pg.page_param] = page
            if pg.size_param:
                params[pg.size_param] = vals["limit"]
        elif pg.style == "offset":
            params[pg.offset_param] = vals["offset"]
            if pg.size_param:
                params[pg.size_param] = vals["limit"]
        elif pg.style == "cursor":
            if pg.size_param:
                params[pg.size_param] = vals["limit"]
            if cursor:
                params[pg.cursor_param] = cursor
        params = {k: v for k, v in params.items() if v != ""}
        if s.auth.style == "query":
            params[s.auth.name] = self.api_key()
        return params

    def build_headers(self) -> dict[str, str]:
        a = self.spec.auth
        h = {"User-Agent": self.config.user_agent, "Accept": "application/json", **self.spec.request.headers}
        if a.style == "bearer":
            h["Authorization"] = f"Bearer {self.api_key()}"
        elif a.style == "header":
            h[a.name] = f"{a.prefix}{self.api_key()}"
        return h

    def search_url(self, query: SearchQuery | None = None) -> str:
        vals = self._values(query or SearchQuery(), 1, "")
        return self.config.base_url + fill(self.spec.request.path, vals, quote_value=True)

    # ---- normalization ------------------------------------------------------
    def _images(self, raw: Any) -> list[str]:
        im = self.spec.images
        urls = raw if isinstance(raw, list) else ([raw] if raw else [])
        ok = [str(u) for u in urls if isinstance(u, str) and host_allowed(u, im.allowed_hosts, im.https_only)]
        return ok[: im.max]

    def normalize_item(self, raw: dict[str, Any]) -> ListingDetail | None:
        s, m = self.spec, self.spec.fields

        def g(t: str, default: Any = None) -> Any:
            v = get_path(raw, m[t]) if t in m else None
            return default if v in (None, "") else v

        native_id, title = g("id"), g("title")
        if native_id is None or title is None:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_.:\-]{1,100}", str(native_id)):
            return None  # ids end up in /v1/listings/{id}: refuse anything that is not a plain token
        title = str(title)[:300]  # bounded: titles feed the O(n^2) dedupe
        url = g("url")
        if url is not None and urlsplit(str(url)).scheme.lower() not in ("http", "https"):
            url = None  # never keep javascript:/data: links from a feed
        text_for_ccy = g("price_range") if "price_range" in m else None
        if "price_range" in m and text_for_ccy is not None:
            rng = parse_price_range(text_for_ccy)
            lo, hi = rng if rng else (Decimal(0), Decimal(0))
        else:
            lo, hi = dec(g("price_min", 0)), dec(g("price_max", g("price_min", 0)))
        scale = Decimal(s.units.price_scale)
        lo, hi = lo * scale, hi * scale
        ccy = normalize_currency_code(g("currency"), s.currency.aliases)
        if ccy is None and s.currency.detect_from_price_text:
            ccy = detect_currency(text_for_ccy, s.currency.aliases)
        ccy = ccy or s.defaults["currency"]
        if s.currency.allowed and ccy not in s.currency.allowed:
            return None
        q = s.quality
        if not price_is_sane(lo, hi, q.min_price, q.max_price, q.max_ratio):
            return None
        moq_d = re.findall(r"\d[\d,]*", str(g("moq", "")))
        unit = g("unit", s.defaults.get("unit"))
        if unit is not None:
            unit = s.units.aliases.get(str(unit).strip().lower(), str(unit).strip())
        verified = str(g("verified", "")).strip().lower() in {"1", "true", "y", "yes"}
        item = build_listing(
            source=s.id, native_id=str(native_id), title=str(title).strip(), price_min=lo, price_max=hi,
            currency=ccy, supplier_native_id=str(g("supplier_id", g("supplier_name", ""))),
            supplier_name=str(g("supplier_name", "")).strip()[:200],
            country=str(g("country", s.defaults.get("country", "CN"))).upper()[:2], city=g("city"),
            url=url, images=self._images(get_path(raw, m["images"]) if "images" in m else None),
            moq=int(dec(moq_d[0])) if moq_d else None, unit=unit, verified=verified,
        )
        update: dict[str, Any] = {}
        if g("description") is not None:
            update["description"] = str(g("description"))
        if g("category") is not None:
            update["category"] = str(g("category"))
        return item.model_copy(update=update) if update else item

    # ---- search with pagination ---------------------------------------------------
    async def search(self, query: SearchQuery) -> list[ListingDetail]:
        pg = self.spec.pagination
        url = self.search_url(query)
        raw_items: list[dict[str, Any]] = []
        page, cursor = pg.first_page, ""
        for n in range(pg.max_pages if pg.style != "none" else 1):
            try:
                payload = await self.fetch(url, self.build_params(query, page, cursor))
            except Exception:
                if n == 0:
                    raise  # first page failure => service degrades to mock with a warning
                log.warning("%s: page %d failed, returning partial results", self.id, n + 1)
                break
            items = self.extract_items(payload)
            raw_items.extend(items)
            if not items or len(raw_items) >= query.limit:
                break
            if pg.style == "cursor":
                nxt = get_path(payload, pg.next_cursor_path)
                if not nxt:
                    break
                cursor = str(nxt)
            else:
                page += 1
        out: list[ListingDetail] = []
        for raw in raw_items:
            try:
                item = self.normalize_item(raw)
            except Exception as exc:
                log.warning("%s: skipped malformed item (%s)", self.id, type(exc).__name__)
                continue
            if item is not None:
                out.append(item)
        deduped = dedupe_listings(out, self.spec.quality.dedupe_threshold)
        return deduped[: query.limit]


def load_licensed_adapters(
    paths: str, *, allow_example: bool = False, env: Mapping[str, str] | None = None
) -> list[LicensedRestAdapter]:
    """Comma-separated mapping paths. A bad file is logged and skipped; it never breaks startup."""
    out: list[LicensedRestAdapter] = []
    for p in (x.strip() for x in paths.split(",")):
        if not p:
            continue
        try:
            spec = load_mapping(p)
            if spec.example and not allow_example:
                raise ValueError("example mapping (fictional provider) refused; copy and edit it")
            out.append(LicensedRestAdapter(spec, env=env))
        except ValueError as exc:
            log.warning("licensed mapping %s skipped: %s", Path(p).name, exc)
    return out
