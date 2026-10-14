"""FastAPI app factory for the trust service."""

import hmac

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ff_trust import SERVICE_NAME, __version__
from ff_trust.adapters.base import SignalsAdapter
from ff_trust.adapters.mock import MockSignalsAdapter
from ff_trust.adapters.real import AlibabaSignalsAdapter, MadeInChinaSignalsAdapter
from ff_trust.api import errors
from ff_trust.api.routes import router
from ff_trust.api.verification_routes import router as verification_router
from ff_trust.cache import TTLCache
from ff_trust.clients.reviews import HttpReviewsClient, MockReviewsClient, ReviewsClient
from ff_trust.config import ScoringConfig, Settings
from ff_trust.obs import install_observability, ready_response
from ff_trust.service import TrustService
from ff_trust.store import ReportStore
from ff_trust.verification import MediaRules, VerificationStore


def _adapter(name: str) -> SignalsAdapter:
    return {"alibaba": AlibabaSignalsAdapter, "made_in_china": MadeInChinaSignalsAdapter}.get(name, MockSignalsAdapter)()


def _reviews(s: Settings) -> ReviewsClient | None:
    if s.reviews_source == "mock":
        return MockReviewsClient()
    if s.reviews_source == "http":
        return HttpReviewsClient(s.reviews_base_url, s.reviews_timeout_seconds, s.reviews_cache_ttl_seconds)
    return None


def create_app(settings: Settings | None = None, adapter: SignalsAdapter | None = None, reviews: ReviewsClient | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Factory Finder trust", version=__version__)
    app.state.settings = settings
    app.state.service = TrustService(
        adapter or _adapter(settings.adapter), ScoringConfig(),
        TTLCache(settings.cache_ttl_seconds, settings.cache_max_entries),
        reports=ReportStore(settings.report_rate_limit, settings.report_rate_window_seconds),
        history_months=settings.history_months, reviews=reviews or _reviews(settings),
        verification=VerificationStore(
            MediaRules(tuple(settings.verification_media_prefixes), tuple(h.lower() for h in settings.verification_media_hosts), settings.verification_allow_http, settings.verification_max_files),
            rate_limit=settings.verification_rate_limit, rate_window=settings.verification_rate_window_seconds,
            max_per_supplier=settings.verification_max_docs_per_supplier, max_per_type=settings.verification_max_docs_per_type,
            max_total=settings.verification_max_total_docs, hash_key=settings.verification_hash_key,
        ),
    )  # fmt: skip
    errors.install(app)

    @app.middleware("http")
    async def internal_token(request: Request, call_next):
        if (
            settings.internal_token
            and request.url.path not in ("/health", "/ready")
            and not hmac.compare_digest(request.headers.get("x-internal-token", ""), settings.internal_token)
        ):
            return JSONResponse({"error": {"code": "forbidden", "message": "Invalid internal token", "details": {}}}, status_code=403)
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME, "version": __version__}

    @app.get("/ready")
    async def ready():
        return ready_response("trust", {})

    app.include_router(router)
    app.include_router(verification_router)
    install_observability(app, "trust")
    return app


app = create_app()
