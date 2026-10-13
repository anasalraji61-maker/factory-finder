"""FastAPI app factory for the trust service."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ff_trust import SERVICE_NAME, __version__
from ff_trust.adapters.base import SignalsAdapter
from ff_trust.adapters.mock import MockSignalsAdapter
from ff_trust.adapters.real import AlibabaSignalsAdapter, MadeInChinaSignalsAdapter
from ff_trust.api import errors
from ff_trust.api.routes import router
from ff_trust.cache import TTLCache
from ff_trust.config import ScoringConfig, Settings
from ff_trust.service import TrustService


def _adapter(name: str) -> SignalsAdapter:
    return {"alibaba": AlibabaSignalsAdapter, "made_in_china": MadeInChinaSignalsAdapter}.get(name, MockSignalsAdapter)()


def create_app(settings: Settings | None = None, adapter: SignalsAdapter | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Factory Finder trust", version=__version__)
    app.state.settings = settings
    app.state.service = TrustService(
        adapter or _adapter(settings.adapter), ScoringConfig(),
        TTLCache(settings.cache_ttl_seconds, settings.cache_max_entries),
    )  # fmt: skip
    errors.install(app)

    @app.middleware("http")
    async def internal_token(request: Request, call_next):
        if (
            settings.internal_token
            and request.url.path != "/health"
            and request.headers.get("x-internal-token") != settings.internal_token
        ):
            return JSONResponse({"error": {"code": "forbidden", "message": "Invalid internal token", "details": {}}}, status_code=403)
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME, "version": __version__}

    app.include_router(router)
    return app


app = create_app()
