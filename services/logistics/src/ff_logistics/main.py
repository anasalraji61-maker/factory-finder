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


def create_app(settings: Settings | None = None, geo: GeoClient | None = None,
               fx: FxService | None = None, freight: FreightRateProvider | None = None) -> FastAPI:
    settings = settings or Settings()
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

    app = FastAPI(title="Factory Finder logistics", version=__version__, lifespan=lifespan)
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
