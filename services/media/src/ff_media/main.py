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

from ff_media import __version__
from ff_media.api.routes import router
from ff_media.config import Settings
from ff_media.db import make_engine
from ff_media.errors import MediaError
from ff_media.obs import db_ready, install_observability, ready_response
from ff_media.service import MediaService
from ff_media.storage import StorageBackend, build_storage


def _err(status: int, code: str, message: str, details: dict | None = None, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "details": details or {}}}, status_code=status, headers=headers
    )



def _require_production_token(token: str | None) -> None:
    """Opt-in fail-closed guard: FF_ENV=production requires FF_INTERNAL_TOKEN (see docs/OPS.md)."""
    if os.environ.get("FF_ENV", "").strip().lower() == "production" and not token:
        raise RuntimeError("FF_ENV=production requires FF_INTERNAL_TOKEN (refusing to start)")


def _require_production_signing_key(settings: Settings) -> None:
    if os.environ.get("FF_ENV", "").strip().lower() == "production" and not settings.signing_key:
        raise RuntimeError("FF_ENV=production requires FF_MEDIA_SIGNING_KEY (refusing to start)")


def create_app(
    settings: Settings | None = None,
    storage: StorageBackend | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    settings = settings or Settings()
    _require_production_token(settings.internal_token or os.environ.get("FF_INTERNAL_TOKEN"))
    _require_production_signing_key(settings)
    token = settings.internal_token or os.environ.get("FF_INTERNAL_TOKEN")
    storage = storage or build_storage(settings)
    engine = make_engine(settings.database_url)
    service = MediaService(engine, settings, storage, clock)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.auto_create_tables:
            await service.create_tables()
        yield
        await engine.dispose()

    app = FastAPI(title="Factory Finder - media", version=__version__, lifespan=lifespan)
    app.state.service = service

    @app.middleware("http")
    async def internal_auth(request: Request, call_next):
        if token and request.url.path not in ("/health", "/ready") and not hmac.compare_digest((request.headers.get("X-Internal-Token", "")).encode(), (token).encode()):
            if request.url.path.startswith("/v1/internal/users/"):  # account export/erasure: invisible to non-internal callers
                return _err(404, "not_found", "Not Found")
            return _err(401, "invalid_internal_token", "Missing or invalid X-Internal-Token")
        return await call_next(request)

    @app.exception_handler(MediaError)
    async def media_error(_: Request, exc: MediaError):
        return _err(exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errs = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        return _err(422, "validation_error", "Invalid request", {"errors": errs})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return _err(exc.status_code, "not_found" if exc.status_code == 404 else "http_error", str(exc.detail))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "media", "version": __version__}

    @app.get("/ready")
    async def ready():
        return ready_response("media", {"database": await db_ready(engine), "storage": await storage.ping()})

    app.include_router(router)
    install_observability(app, "media")
    return app


app = create_app()
