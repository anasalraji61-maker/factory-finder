from __future__ import annotations

import asyncio
import hmac
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ff_tracking import __version__, repository
from ff_tracking.adapters.base import TrackingProvider
from ff_tracking.adapters.http import (
    HttpAwbProvider,
    HttpContainerProvider,
    HttpVesselPositionProvider,
)
from ff_tracking.adapters.mock import MockProvider
from ff_tracking.adapters.real import LicensedProviderStub
from ff_tracking.adapters.router import FallbackProvider, RoutingProvider
from ff_tracking.api.routes import router
from ff_tracking.config import Settings
from ff_tracking.domain.errors import DomainError, RefreshThrottled, Unauthenticated
from ff_tracking.jobs import RefreshJob
from ff_tracking.obs import db_ready, install_observability, ready_response
from ff_tracking.relay import NotifyClient, build_relay
from ff_tracking.repository import ShipmentRepository, make_engine
from ff_tracking.service import ShipmentService


def _err(status: int, code: str, message: str, details: dict | None = None, headers: dict | None = None):
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}},
                        status_code=status, headers=headers)


def build_provider(settings: Settings) -> TrackingProvider:
    """mock (default) | http (licensed APIs, mock fallback with a warning) | stub for anything else."""
    if settings.provider == "mock":
        return MockProvider()
    if settings.provider != "http":
        return LicensedProviderStub(settings.provider, settings.provider_api_key)
    kw = {"min_interval_s": settings.http_min_interval_seconds, "cache_ttl_s": settings.http_cache_ttl_seconds}
    router = RoutingProvider(
        container=HttpContainerProvider(settings.container_base_url, settings.container_api_key or "", **kw),
        awb=HttpAwbProvider(settings.awb_base_url, settings.awb_api_key or "", **kw),
        vessel=HttpVesselPositionProvider(settings.vessel_base_url, settings.vessel_api_key or "", **kw),
    )
    return FallbackProvider(router, MockProvider()) if settings.fallback_to_mock else router



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
    provider: TrackingProvider | None = None,
    clock: Callable[[], datetime] | None = None,
    notify_client: NotifyClient | None = None,
) -> FastAPI:
    settings = settings or Settings()
    _require_production_token(settings.internal_token or os.environ.get("FF_INTERNAL_TOKEN"))
    provider = provider or build_provider(settings)
    repo = ShipmentRepository(make_engine(settings.database_url))
    clock = clock or (lambda: datetime.now(UTC))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_create_tables:
            await repo.create_tables()
        task = None
        if settings.refresh_job_enabled:
            job = RefreshJob(repo, app.state.service, clock, settings.refresh_job_interval_hours,
                             settings.refresh_job_batch_size)
            task = asyncio.create_task(job.run_forever(settings.refresh_job_poll_seconds))
        relay_task = None
        if app.state.relay:
            relay_task = asyncio.create_task(app.state.relay.run_forever(settings.notify_poll_seconds))
        yield
        for t in (task, relay_task):
            if t:
                t.cancel()
        await repo.engine.dispose()

    app = FastAPI(**_docs_kwargs(), title="Factory Finder - tracking", version=__version__, lifespan=lifespan)
    app.state.service = ShipmentService(repo, provider, clock, settings.refresh_min_interval_seconds,
                                       settings.max_shipments_per_user)
    app.state.relay = build_relay(settings, repo, clock, notify_client)
    token = settings.internal_token or os.environ.get("FF_INTERNAL_TOKEN")

    @app.middleware("http")
    async def internal_auth(request: Request, call_next):
        if token and request.url.path not in ("/health", "/ready") and not hmac.compare_digest((request.headers.get("X-Internal-Token", "")).encode(), (token).encode()):
            if request.url.path.startswith("/v1/internal/users/"):  # account export/erasure: invisible to non-internal callers
                return _err(404, "not_found", "Not Found")
            return _err(401, "invalid_internal_token", "Missing or invalid X-Internal-Token")
        return await call_next(request)

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError):
        headers = {"Retry-After": str(exc.retry_after_seconds)} if isinstance(exc, RefreshThrottled) else None
        return _err(exc.status_code, exc.code, exc.message, exc.details, headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errs = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        return _err(422, "validation_error", "Invalid request", {"errors": errs})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return _err(exc.status_code, "not_found" if exc.status_code == 404 else "http_error", str(exc.detail))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "tracking", "version": __version__}

    @app.get("/ready")
    async def ready():
        return ready_response("tracking", {"database": await db_ready(repo.engine)})

    @app.get("/v1/internal/outbox-status")
    async def outbox_status() -> dict:
        """Relay/outbox counters (internal; guarded by X-Internal-Token when set)."""
        return {"relay": "on" if app.state.relay else "off", **await repo.outbox_stats()}

    @app.post("/v1/internal/users/{user_id}/export")
    async def export_user(user_id: str) -> dict:
        return {"service": "tracking", "user_id": user_id, **await repository.export_owner(repo.engine, user_id)}

    @app.delete("/v1/internal/users/{user_id}/data")
    async def erase_user(user_id: str) -> dict:
        return {"service": "tracking", "user_id": user_id, "status": "done", "counts": await repository.erase_owner(repo.engine, user_id)}

    app.include_router(router)
    install_observability(app, "tracking")
    return app


app = create_app()
__all__ = ["Unauthenticated", "app", "create_app"]
