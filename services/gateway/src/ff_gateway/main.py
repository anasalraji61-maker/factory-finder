"""Gateway app factory."""

import logging
import re
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ff_gateway import SERVICE_NAME, __version__
from ff_gateway.api import auth, me, proxy, ws
from ff_gateway.clients.home import HomeClient, HttpHomeClient, MockHomeClient
from ff_gateway.config import Settings
from ff_gateway.db import create_tables, make_engine, make_sessionmaker
from ff_gateway.domain.clock import Clock, SystemClock
from ff_gateway.domain.errors import GatewayError, RateLimited
from ff_gateway.domain.rate_limit import RateLimiter
from ff_gateway.domain.security import TokenService

log = logging.getLogger("ff_gateway")


class _RedactToken(logging.Filter):
    """The WebSocket client may pass ?token=<jwt>; keep it out of uvicorn access logs."""

    _re = re.compile(r"([?&]token=)[^&\s\"']+")

    def filter(self, record: logging.LogRecord) -> bool:
        record.args = tuple(self._re.sub(r"\1[redacted]", a) if isinstance(a, str) else a for a in record.args or ())
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactToken())


def _error(status: int, code: str, message: str, details: dict | None = None, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}}, status_code=status, headers=headers)


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    http_client: httpx.AsyncClient | None = None,
    home_client: HomeClient | None = None,
) -> FastAPI:
    settings = settings or Settings()
    clock = clock or SystemClock()
    engine = make_engine(settings.database_url)
    http = http_client or httpx.AsyncClient(timeout=settings.upstream_timeout_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await create_tables(engine)
        yield
        await http.aclose()
        await engine.dispose()

    app = FastAPI(title="Factory Finder gateway", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.clock = clock
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.http = http
    app.state.tokens = TokenService(
        settings.resolved_secret(), clock, settings.access_ttl_seconds, settings.refresh_ttl_seconds, settings.jwt_algorithm
    )  # fmt: skip
    app.state.home_client = home_client or (
        MockHomeClient() if settings.home_client == "mock" else HttpHomeClient(http, settings.upstream_map())
    )
    limiter = RateLimiter(clock)

    @app.exception_handler(GatewayError)
    async def _gw(_: Request, e: GatewayError) -> JSONResponse:
        return _error(e.status_code, e.code, e.message, e.details, e.headers)

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, e: RequestValidationError) -> JSONResponse:
        errs = [
            {"field": ".".join(str(x) for x in i["loc"][1:]) or str(i["loc"][0]), "location": str(i["loc"][0]), "message": i["msg"], "type": i["type"]}
            for i in e.errors()
        ]  # fmt: skip
        return _error(422, "validation_error", "Request validation failed", {"errors": errs})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "http_error")
        return _error(e.status_code, code, str(e.detail))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return _error(500, "internal_error", "Internal server error")

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        path = request.url.path
        if path != "/health" and request.method != "OPTIONS":
            auth_route = path.startswith("/v1/auth")
            limit = settings.auth_rate_limit_per_minute if auth_route else settings.rate_limit_per_minute
            ip = request.client.host if request.client else "unknown"
            wait = limiter.check(f"{'auth' if auth_route else 'api'}:{ip}", limit)
            if wait is not None:
                e = RateLimited(wait, limit)
                return _error(e.status_code, e.code, e.message, e.details, e.headers)
        return await call_next(request)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME, "version": __version__}

    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(ws.router)
    app.include_router(proxy.router)  # catch-all, must be last
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"],
        expose_headers=["X-Request-Id"], allow_credentials=False,
    )  # fmt: skip
    return app


app = create_app()
