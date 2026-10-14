"""FastAPI app factory. ``app = create_app()`` for uvicorn."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ff_notifications.adapters.push import FcmPushAdapter, MockPushAdapter, PushAdapter
from ff_notifications.api.routes import router
from ff_notifications.clients.sourcing import HttpSourcingClient, MockSourcingClient, SourcingClient
from ff_notifications.config import Settings
from ff_notifications.errors import ApiError
from ff_notifications.obs import db_ready, install_observability, ready_response
from ff_notifications.persistence.store import Store
from ff_notifications.service import NotificationService

VERSION = "0.1.0"


def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "details": details or {}}}, status_code=status
    )


def create_app(
    settings: Settings | None = None,
    *,
    sourcing: SourcingClient | None = None,
    push: PushAdapter | None = None,
) -> FastAPI:
    settings = settings or Settings()
    store = Store(settings.database_url)
    if sourcing is None:
        sourcing = (
            MockSourcingClient()
            if settings.use_mock_sourcing
            else HttpSourcingClient(settings.sourcing_base_url, settings.sourcing_timeout_seconds)
        )
    if push is None:
        push = (
            FcmPushAdapter(settings.fcm_enabled)
            if settings.push_provider == "fcm"
            else MockPushAdapter()
        )
    service = NotificationService(store=store, sourcing=sourcing, push=push, settings=settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.auto_create_tables:
            await store.create_all()
        task = asyncio.create_task(service.run_scheduler()) if settings.scheduler_enabled else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if hasattr(sourcing, "aclose"):
            await sourcing.aclose()
        await store.dispose()

    app = FastAPI(title="Factory Finder notifications", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.service = service

    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError):
        return _error(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errs = [{"loc": [str(x) for x in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        return _error(422, "validation_error", "Request validation failed", {"errors": errs})

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException):
        return _error(
            exc.status_code,
            "not_found" if exc.status_code == 404 else "http_error",
            str(exc.detail),
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "notifications", "version": VERSION}

    @app.get("/ready")
    async def ready():
        return ready_response("notifications", {"database": await db_ready(store.engine)})

    app.include_router(router)
    install_observability(app, "notifications")
    return app


app = create_app()
