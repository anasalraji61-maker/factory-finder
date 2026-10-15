"""FastAPI app factory. ``app = create_app()`` for uvicorn (port 8114)."""

from __future__ import annotations

import hmac
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ff_freight import __version__
from ff_freight.api import admin, internal, router
from ff_freight.config import Settings
from ff_freight.db import make_engine, now
from ff_freight.errors import ApiError
from ff_freight.obs import db_ready, install_observability, ready_response
from ff_freight.service import FreightService


def _err(status: int, code: str, message: str, details: dict | None = None, headers: dict | None = None):
    return JSONResponse(
        {"error": {"code": code, "message": message, "details": details or {}}},
        status_code=status,
        headers=headers,
    )


def _require_production_token(token: str | None) -> None:
    """Opt-in fail-closed guard: FF_ENV=production requires FF_INTERNAL_TOKEN (see docs/OPS.md)."""
    if os.environ.get("FF_ENV", "").strip().lower() == "production" and not token:
        raise RuntimeError("FF_ENV=production requires FF_INTERNAL_TOKEN (refusing to start)")


def _docs_kwargs() -> dict[str, None]:
    """FF_ENV=production: no /docs, /redoc or /openapi.json (the schema lives in contracts/)."""
    if os.environ.get("FF_ENV", "").strip().lower() == "production":
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {}


def create_app(settings: Settings | None = None, clock: Callable[[], datetime] | None = None) -> FastAPI:
    settings = settings or Settings()
    token = settings.internal_token_value or os.environ.get("FF_INTERNAL_TOKEN") or None
    _require_production_token(token)
    engine = make_engine(settings.database_url)
    service = FreightService(engine, settings, clock or now)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.auto_create_tables:
            await service.create_all()
        yield
        await engine.dispose()

    app = FastAPI(**_docs_kwargs(), title="Factory Finder - freight", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service

    @app.middleware("http")
    async def internal_auth(request: Request, call_next):
        if (
            token
            and request.url.path not in ("/health", "/ready")
            and not hmac.compare_digest(request.headers.get("X-Internal-Token", "").encode(), token.encode())
        ):
            if request.url.path.startswith("/v1/internal/"):  # account export/erasure: invisible to non-internal callers
                return _err(404, "not_found", "Not Found")
            return _err(401, "invalid_internal_token", "Missing or invalid X-Internal-Token")
        return await call_next(request)

    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError):
        return _err(exc.status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errs = [{"loc": [str(x) for x in e["loc"]], "msg": str(e["msg"])} for e in exc.errors()]
        return _err(422, "validation_error", "Request validation failed", {"errors": errs})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return _err(exc.status_code, "not_found" if exc.status_code == 404 else "http_error", str(exc.detail))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "freight", "version": __version__}

    @app.get("/ready")
    async def ready():
        return ready_response("freight", {"database": await db_ready(engine)})

    app.include_router(router)
    app.include_router(admin)
    app.include_router(internal)
    install_observability(app, "freight")
    return app


app = create_app()
