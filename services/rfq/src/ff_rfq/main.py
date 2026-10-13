from __future__ import annotations

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
from ff_rfq.domain.errors import DomainError
from ff_rfq.service import RfqService


def _err(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}}, status_code=status)


def create_app(
    settings: Settings | None = None,
    sourcing: SourcingClient | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    if sourcing is None:
        sourcing = (MockSourcingClient() if settings.sourcing_client == "mock"
                    else HttpSourcingClient(settings.sourcing_url))
    engine = make_engine(settings.database_url)
    service = RfqService(engine, settings, sourcing, clock or (lambda: datetime.now(UTC)))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await service.create_tables()
        yield
        await engine.dispose()

    app = FastAPI(title="Factory Finder - rfq", version=__version__, lifespan=lifespan)
    app.state.service = service
    token = settings.internal_token or os.environ.get("FF_INTERNAL_TOKEN")

    @app.middleware("http")
    async def internal_auth(request: Request, call_next):
        if token and request.url.path != "/health" and request.headers.get("X-Internal-Token") != token:
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

    app.include_router(router)
    return app


app = create_app()
