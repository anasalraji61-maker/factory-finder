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

from ff_rfq import __version__
from ff_rfq.api.routes import router
from ff_rfq.clients.sourcing import HttpSourcingClient, MockSourcingClient, SourcingClient
from ff_rfq.config import Settings
from ff_rfq.db import make_engine
from ff_rfq.deals import DealService
from ff_rfq.domain.errors import DomainError
from ff_rfq.obs import db_ready, install_observability, ready_response
from ff_rfq.reviews import ReviewService
from ff_rfq.service import RfqService


def _err(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}}, status_code=status)



def _require_production_token(token: str | None) -> None:
    """Opt-in fail-closed guard: FF_ENV=production requires FF_INTERNAL_TOKEN (see docs/OPS.md)."""
    if os.environ.get("FF_ENV", "").strip().lower() == "production" and not token:
        raise RuntimeError("FF_ENV=production requires FF_INTERNAL_TOKEN (refusing to start)")


def create_app(
    settings: Settings | None = None,
    sourcing: SourcingClient | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    _require_production_token(settings.internal_token or os.environ.get("FF_INTERNAL_TOKEN"))
    if sourcing is None:
        sourcing = (MockSourcingClient() if settings.sourcing_client == "mock"
                    else HttpSourcingClient(settings.sourcing_url))
    engine = make_engine(settings.database_url)
    service = RfqService(engine, settings, sourcing, clock or (lambda: datetime.now(UTC)))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.auto_create_tables:
            await service.create_tables()
        yield
        await engine.dispose()

    app = FastAPI(title="Factory Finder - rfq", version=__version__, lifespan=lifespan)
    app.state.service = service
    app.state.reviews = ReviewService(engine, service.clock)
    app.state.deals = DealService(engine, service.clock, settings.require_both_invoices)
    token = settings.internal_token or os.environ.get("FF_INTERNAL_TOKEN")
    app.state.internal_token = token

    @app.middleware("http")
    async def internal_auth(request: Request, call_next):
        if token and request.url.path not in ("/health", "/ready") and not hmac.compare_digest((request.headers.get("X-Internal-Token", "")).encode(), (token).encode()):
            if request.url.path.startswith("/v1/internal/users/"):  # account export/erasure: invisible to non-internal callers
                return _err(404, "not_found", "Not Found")
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
        return {"status": "ok", "service": "rfq", "version": __version__}

    @app.get("/ready")
    async def ready():
        return ready_response("rfq", {"database": await db_ready(engine)})

    app.include_router(router)
    install_observability(app, "rfq")
    return app


app = create_app()
