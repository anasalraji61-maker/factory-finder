"""FastAPI app factory. ``app = create_app()`` for uvicorn."""

from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from ff_notifications.adapters.email import EmailProvider, MockEmail, SmtpEmail
from ff_notifications.adapters.push import (
    FcmPush,
    MockPush,
    PushProvider,
    ServiceAccountTokenProvider,
)
from ff_notifications.api.routes import router
from ff_notifications.clients.sourcing import HttpSourcingClient, MockSourcingClient, SourcingClient
from ff_notifications.config import Settings
from ff_notifications.errors import ApiError
from ff_notifications.i18n import message_ar
from ff_notifications.obs import db_ready, install_observability, ready_response
from ff_notifications.persistence.store import Store
from ff_notifications.service import NotificationService

VERSION = "0.1.0"


def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "message_ar": message_ar(code),
                "details": details or {},
            }
        },
        status_code=status,
    )


def build_push(settings: Settings) -> PushProvider | None:
    mode = settings.notify_push.lower()
    if mode == "mock":
        return MockPush()
    if mode == "fcm" and settings.fcm_project_id:
        creds = settings.fcm_credentials_json
        return FcmPush(
            settings.fcm_project_id,
            ServiceAccountTokenProvider(
                creds.get_secret_value() if creds else None, settings.fcm_credentials_file
            ),
        )
    return None  # off (or fcm without a project id)


def build_email(settings: Settings) -> EmailProvider | None:
    mode = settings.notify_email.lower()
    if mode == "mock":
        return MockEmail()
    if mode == "smtp" and settings.smtp_host and settings.smtp_from:
        pw = settings.smtp_password
        return SmtpEmail(
            settings.smtp_host,
            settings.smtp_port,
            settings.smtp_from,
            settings.smtp_user,
            pw.get_secret_value() if pw else None,
        )
    return None



def _require_production_token(token: str | None) -> None:
    """Opt-in fail-closed guard: FF_ENV=production requires FF_INTERNAL_TOKEN (see docs/OPS.md)."""
    if os.environ.get("FF_ENV", "").strip().lower() == "production" and not token:
        raise RuntimeError("FF_ENV=production requires FF_INTERNAL_TOKEN (refusing to start)")


def _docs_kwargs() -> dict[str, None]:
    """FF_ENV=production: no /docs, /redoc or /openapi.json (the schema lives in contracts/)."""
    if os.environ.get("FF_ENV", "").strip().lower() == "production":
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {}


def create_app(
    settings: Settings | None = None,
    *,
    sourcing: SourcingClient | None = None,
    push: PushProvider | None = None,
    email: EmailProvider | None = None,
) -> FastAPI:
    settings = settings or Settings()
    _require_production_token(settings.internal_token_value)
    store = Store(settings.database_url)
    if sourcing is None:
        sourcing = (
            MockSourcingClient()
            if settings.use_mock_sourcing
            else HttpSourcingClient(settings.sourcing_base_url, settings.sourcing_timeout_seconds)
        )
    if push is None:
        push = build_push(settings)
    if email is None:
        email = build_email(settings)
    service = NotificationService(
        store=store, sourcing=sourcing, push=push, email=email, settings=settings
    )

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

    app = FastAPI(
        **_docs_kwargs(), title="Factory Finder notifications", version=VERSION, lifespan=lifespan
    )
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
