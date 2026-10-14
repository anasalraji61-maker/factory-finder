"""FastAPI app factory. ``app = create_app()`` for uvicorn."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ff_messaging.api.routes import router
from ff_messaging.config import Settings
from ff_messaging.domain import errors as E
from ff_messaging.domain.rate_limit import SlidingWindowRateLimiter
from ff_messaging.domain.rules import TypingThrottle
from ff_messaging.domain.safety import (
    AbuseFilter,
    AttachmentRules,
    ContentPolicy,
    load_default_abuse_terms,
)
from ff_messaging.persistence.database import Database
from ff_messaging.realtime.hub import ConversationHub
from ff_messaging.service import MessagingService

VERSION = "0.1.0"

_STATUS: dict[type, int] = {
    E.BadRequestError: 400,
    E.InvalidInputError: 422,
    E.UnauthenticatedError: 401,
    E.ForbiddenError: 403,
    E.NotFoundError: 404,
    E.RateLimitedError: 429,
}


def _error(
    status: int, code: str, message: str, details: dict | None = None, headers: dict | None = None
):
    return JSONResponse(
        {"error": {"code": code, "message": message, "details": details or {}}},
        status_code=status,
        headers=headers,
    )


def build_service(settings: Settings, db: Database, hub: ConversationHub) -> MessagingService:
    terms = settings.abuse_terms if settings.abuse_terms is not None else load_default_abuse_terms()
    terms = [*terms, *settings.abuse_terms_extra]
    policy = ContentPolicy(
        max_text_length=settings.max_text_length,
        max_title_length=settings.max_title_length,
        abuse_filter=AbuseFilter(terms if settings.abuse_filter_enabled else []),
        abuse_action=settings.abuse_action,
        attachment_rules=AttachmentRules(
            max_bytes=settings.attachment_max_bytes,
            allowed_mime_types=tuple(settings.attachment_allowed_mime_types),
            allow_http=settings.attachment_allow_http,
            allowed_hosts=tuple(settings.attachment_allowed_hosts),
        ),
    )
    limiter = SlidingWindowRateLimiter(
        limit=settings.send_rate_limit, window_seconds=settings.send_rate_window_seconds
    )
    return MessagingService(db=db, settings=settings, policy=policy, limiter=limiter, publisher=hub)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings.database_url, echo=settings.database_echo)
    hub = ConversationHub(
        queue_size=settings.ws_queue_size, max_per_user=settings.ws_max_connections_per_user
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if settings.auto_create_tables:
            await db.create_all()
        yield
        await db.dispose()

    app = FastAPI(title="Factory Finder messaging", version=VERSION, lifespan=lifespan)
    app.state.settings = settings
    app.state.db = db
    app.state.hub = hub
    app.state.typing = TypingThrottle(interval_seconds=settings.typing_throttle_seconds)
    app.state.service = build_service(settings, db, hub)

    @app.exception_handler(E.MessagingError)
    async def _domain(_: Request, exc: E.MessagingError):
        headers = None
        if isinstance(exc, E.RateLimitedError):
            headers = {"Retry-After": str(int(exc.retry_after_seconds) + 1)}
        return _error(_STATUS.get(type(exc), 400), exc.code, exc.message, exc.details, headers)

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
        return {"status": "ok", "service": "messaging", "version": VERSION}

    app.include_router(router)
    return app


app = create_app()
