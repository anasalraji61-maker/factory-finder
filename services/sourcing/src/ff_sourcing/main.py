from __future__ import annotations

from fastapi import FastAPI

from . import __version__
from .adapters.registry import AdapterRegistry, build_registry
from .api.errors import install_error_handlers
from .api.routes import router
from .clients.trust import HttpTrustClient, MockTrustClient, NullTrustClient, TrustClient
from .config import Settings
from .service import SourcingService


def build_trust(settings: Settings) -> TrustClient:
    if settings.trust_mode == "http":
        return HttpTrustClient(settings.trust_base_url, settings.trust_timeout_s)
    if settings.trust_mode == "off":
        return NullTrustClient()
    return MockTrustClient()


def create_app(
    settings: Settings | None = None,
    registry: AdapterRegistry | None = None,
    trust: TrustClient | None = None,
) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Factory Finder - sourcing", version=__version__)
    app.state.service = SourcingService(
        registry or build_registry(settings),
        trust or build_trust(settings),
        adapter_timeout_s=settings.adapter_timeout_s,
        cache_ttl_s=settings.cache_ttl_s,
        trust_cache_ttl_s=settings.trust_cache_ttl_s,
    )
    install_error_handlers(app)
    app.include_router(router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "service": "sourcing", "version": __version__}

    return app


app = create_app()
