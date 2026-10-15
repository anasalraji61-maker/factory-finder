import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from .adapters.freight import FreightRateProvider, HttpFreightProvider, MockFreight
from .adapters.fx import EcbFx, FxService, MockFx
from .api.routes import router
from .clients.geo import CachedGeo, GeoClient, HttpGeo, MockGeo
from .config import Settings
from .errors import install_handlers
from .obs import install_observability, ready_response


def _docs_kwargs() -> dict[str, None]:
    """FF_ENV=production: no /docs, /redoc or /openapi.json (the schema lives in contracts/)."""
    if os.environ.get("FF_ENV", "").strip().lower() == "production":
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {}


def _require_production_token(token: str | None) -> None:
    """Opt-in fail-closed guard: FF_ENV=production requires FF_INTERNAL_TOKEN (see docs/OPS.md)."""
    if os.environ.get("FF_ENV", "").strip().lower() == "production" and not token:
        raise RuntimeError("FF_ENV=production requires FF_INTERNAL_TOKEN (refusing to start)")


def create_app(settings: Settings | None = None, geo: GeoClient | None = None,
               fx: FxService | None = None, freight: FreightRateProvider | None = None) -> FastAPI:
    settings = settings or Settings()
    _require_production_token(settings.internal_token or os.environ.get("FF_INTERNAL_TOKEN"))
    geo = geo or (MockGeo() if settings.geo_provider == "mock" else
                  CachedGeo(HttpGeo(settings.geo_url), settings.geo_cache_ttl_seconds))
    if fx is None:
        provider = EcbFx(settings.fx_url, settings.fx_cache_ttl_seconds) if settings.fx_provider == "ecb" else MockFx()
        fx = FxService(provider)

    if freight is None:
        freight = (HttpFreightProvider(settings.freight_url, settings.freight_api_key,
                                       min_interval_s=settings.freight_min_interval_s,
                                       cache_ttl_s=settings.freight_cache_ttl_seconds)
                   if settings.freight_provider == "http" and settings.freight_url else MockFreight())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        client = getattr(geo, "_client", None)
        if client is not None:
            await client.aclose()

    app = FastAPI(**_docs_kwargs(), title="Factory Finder logistics", version=__version__, lifespan=lifespan)
    app.state.settings, app.state.geo, app.state.fx = settings, geo, fx
    app.state.freight = freight
    install_handlers(app)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "logistics", "version": __version__}

    @app.get("/ready")
    async def ready():
        return ready_response("logistics", {})

    app.include_router(router)
    install_observability(app, "logistics")
    return app


app = create_app()
