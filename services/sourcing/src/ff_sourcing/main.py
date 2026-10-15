from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import __version__
from .adapters.native import NativeAdapter, NativeStore
from .adapters.registry import AdapterRegistry, build_registry
from .api.errors import install_error_handlers
from .api.internal import router as internal_router
from .api.moderation import admin as admin_router
from .api.moderation import router as moderation_router
from .api.my import router as my_router
from .api.routes import router
from .clients.trust import HttpTrustClient, MockTrustClient, NullTrustClient, TrustClient
from .config import Settings
from .db import make_engine
from .domain.models import SupplierSummary
from .native_service import NativeService
from .obs import db_ready, install_observability, ready_response
from .price_history import PriceHistoryStore
from .service import SourcingService


def build_trust(settings: Settings) -> TrustClient:
    if settings.trust_mode == "http":
        return HttpTrustClient(settings.trust_base_url, settings.trust_timeout_s)
    if settings.trust_mode == "off":
        return NullTrustClient()
    return MockTrustClient()



def _require_production_token(token: str | None) -> None:
    """Opt-in fail-closed guard: FF_ENV=production requires FF_INTERNAL_TOKEN (see docs/OPS.md)."""
    if os.environ.get("FF_ENV", "").strip().lower() == "production" and not token:
        raise RuntimeError("FF_ENV=production requires FF_INTERNAL_TOKEN (refusing to start)")


def create_app(
    settings: Settings | None = None,
    registry: AdapterRegistry | None = None,
    trust: TrustClient | None = None,
) -> FastAPI:
    settings = settings or Settings()
    _require_production_token(settings.internal_token or os.environ.get("FF_INTERNAL_TOKEN"))
    registry = registry or build_registry(settings)
    trust = trust or build_trust(settings)
    engine = make_engine(settings.database_url)
    store = NativeStore(engine, settings.auto_create_tables)
    native_adapter = NativeAdapter(store)
    registry.register(native_adapter)  # the native source is always on (it is our own data)
    registry.enable("native")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await store.ensure_ready()
        yield
        await engine.dispose()

    app = FastAPI(title="Factory Finder - sourcing", version=__version__, lifespan=lifespan)
    service = SourcingService(
        registry,
        trust,
        adapter_timeout_s=settings.adapter_timeout_s,
        cache_ttl_s=settings.cache_ttl_s,
        trust_cache_ttl_s=settings.trust_cache_ttl_s,
    )
    service.history = PriceHistoryStore(
        engine,
        settings.auto_create_tables,
        settings.price_history_dedupe_hours,
        settings.price_history_max_points,
        settings.price_history_retention_days,
    )
    app.state.service = service

    async def resolve_supplier(supplier_id: str):
        for a in registry.enabled():
            if a.id == "native":
                continue
            sup = await a.get_supplier(supplier_id)
            if sup is not None:
                return SupplierSummary(**sup.model_dump(include=set(SupplierSummary.model_fields)))
        return None

    native_adapter.resolver = resolve_supplier
    app.state.native = NativeService(
        native_adapter,
        trust,
        settings.max_listings_per_supplier,
        settings.create_rate_per_hour,
        settings.report_rate_per_hour,
        settings.report_review_threshold,
        settings.reporter_hash_key,
    )
    native_service = app.state.native
    native_service.on_change = service.history.record_listings
    app.state.admin_token = settings.admin_token.get_secret_value() if settings.admin_token else None
    token = settings.internal_token or os.environ.get("FF_INTERNAL_TOKEN")

    @app.middleware("http")
    async def internal_auth(request: Request, call_next):
        # /v1/my/*, reports and admin tools trust gateway-set identity headers (X-Supplier-Id, X-User-Id):
        # when an internal token is configured, calls without it are rejected (mirrors rfq).
        path = request.url.path
        if (
            token
            and (path.startswith(("/v1/my", "/v1/admin", "/v1/internal")) or path.endswith("/report"))
            and not hmac.compare_digest((request.headers.get("X-Internal-Token", "")).encode(), (token).encode())
        ):
            if path.startswith("/v1/internal/"):  # account export/erasure: invisible to non-internal callers
                return JSONResponse({"error": {"code": "not_found", "message": "Not Found", "details": {}}}, status_code=404)
            body = {"error": {"code": "invalid_internal_token", "message": "Missing or invalid X-Internal-Token", "details": {}}}
            return JSONResponse(body, status_code=401)
        return await call_next(request)

    install_error_handlers(app)
    app.include_router(router)
    app.include_router(my_router)
    app.include_router(internal_router)
    app.include_router(moderation_router)
    app.include_router(admin_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "sourcing", "version": __version__}

    @app.get("/ready")
    async def ready() -> object:
        return ready_response("sourcing", {"database": await db_ready(engine)})

    install_observability(app, "sourcing")
    return app


app = create_app()
