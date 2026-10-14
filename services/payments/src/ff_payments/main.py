from __future__ import annotations

import hmac
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ff_payments import __version__
from ff_payments.api.routes import router
from ff_payments.clients.deals import DealClient, HttpDealClient, MockDealClient
from ff_payments.config import Settings
from ff_payments.db import make_engine
from ff_payments.domain.errors import DomainError
from ff_payments.obs import db_ready, install_observability, ready_response
from ff_payments.providers.base import PaymentProvider
from ff_payments.providers.registry import build_provider
from ff_payments.service import PaymentsService

WEBHOOK_PREFIX = "/v1/payments/webhooks/"


def _err(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}}, status_code=status)



def _require_production_token(token: str | None) -> None:
    """Opt-in fail-closed guard: FF_ENV=production requires FF_INTERNAL_TOKEN (see docs/OPS.md)."""
    if os.environ.get("FF_ENV", "").strip().lower() == "production" and not token:
        raise RuntimeError("FF_ENV=production requires FF_INTERNAL_TOKEN (refusing to start)")


def create_app(
    settings: Settings | None = None,
    provider: PaymentProvider | None = None,
    deals: DealClient | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    _require_production_token(settings.internal_token or os.environ.get("FF_INTERNAL_TOKEN"))
    token = settings.internal_token or os.environ.get("FF_INTERNAL_TOKEN")
    if provider is None:
        provider = build_provider(settings)
    if deals is None:
        deals = (MockDealClient() if settings.deal_client == "mock"
                 else HttpDealClient(settings.rfq_url, token))
    engine = make_engine(settings.database_url)
    service = PaymentsService(engine, settings, provider, deals, clock or (lambda: datetime.now(UTC)))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.auto_create_tables:
            await service.create_tables()
        yield
        await engine.dispose()

    app = FastAPI(title="Factory Finder - payments", version=__version__, lifespan=lifespan)
    app.state.service = service

    @app.middleware("http")
    async def internal_auth(request: Request, call_next):
        path = request.url.path
        exempt = path in ("/health", "/ready") or path.startswith(WEBHOOK_PREFIX)  # webhooks: HMAC instead
        if token and not exempt and not hmac.compare_digest(request.headers.get("X-Internal-Token", ""), token):
            return _err(401, "invalid_internal_token", "Missing or invalid X-Internal-Token")
        return await call_next(request)

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError):
        return _err(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errs = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        return _err(422, "validation_error", "Invalid request", {"errors": errs})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return _err(exc.status_code, "not_found" if exc.status_code == 404 else "http_error", str(exc.detail))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "payments", "version": __version__}

    @app.get("/ready")
    async def ready():
        return ready_response("payments", {"database": await db_ready(engine)})

    app.include_router(router)
    install_observability(app, "payments")
    return app


app = create_app()
