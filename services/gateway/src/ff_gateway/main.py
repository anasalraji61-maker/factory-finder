"""Gateway app factory."""

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ff_gateway import SERVICE_NAME, __version__
from ff_gateway.api import (
    account,
    admin,
    admin_demand,
    admin_media,
    admin_moderation,
    admin_payments,
    admin_services,
    auth,
    me,
    proxy,
    ws,
)
from ff_gateway.api.deps import bearer_token
from ff_gateway.clients.home import HomeClient, HttpHomeClient, MockHomeClient
from ff_gateway.config import Settings
from ff_gateway.db import create_tables, make_engine, make_sessionmaker
from ff_gateway.domain import privacy
from ff_gateway.domain.client_ip import client_ip
from ff_gateway.domain.clock import Clock, SystemClock
from ff_gateway.domain.errors import GatewayError, RateLimited
from ff_gateway.domain.mail import build_mailer
from ff_gateway.domain.rate_limit import build_limit_store
from ff_gateway.domain.security import TokenService
from ff_gateway.domain.ws_tickets import WsTicketStore
from ff_gateway.obs import db_ready, install_observability, ready_response

log = logging.getLogger("ff_gateway")


class _RedactToken(logging.Filter):
    """The WebSocket client may pass ?token=<jwt>; keep it out of uvicorn access logs."""

    _re = re.compile(r"([?&]token=)[^&\s\"']+")

    def filter(self, record: logging.LogRecord) -> bool:
        record.args = tuple(
            self._re.sub(r"\1[redacted]", a) if isinstance(a, str) else a for a in record.args or ()
        )
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactToken())


def _error(
    status: int, code: str, message: str, details: dict | None = None, headers: dict | None = None
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "details": details or {}}},
        status_code=status,
        headers=headers,
    )


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    http_client: httpx.AsyncClient | None = None,
    home_client: HomeClient | None = None,
    redis_client: object | None = None,
    mailer: object | None = None,
) -> FastAPI:
    settings = settings or Settings()
    if os.environ.get("FF_ENV", "").strip().lower() == "production":  # opt-in fail-closed guard (docs/OPS.md)
        missing = [
            n for n, v in (
                ("FF_GATEWAY_JWT_SECRET", settings.jwt_secret),
                ("FF_GATEWAY_ADMIN_TOKEN", settings.admin_token),
            ) if not v
        ]  # fmt: skip
        if missing:
            raise RuntimeError(f"FF_ENV=production requires {', '.join(missing)} to be set (refusing to start)")
    clock = clock or SystemClock()
    engine = make_engine(settings.database_url)
    http = http_client or httpx.AsyncClient(timeout=settings.upstream_timeout_seconds)

    async def deletion_worker() -> None:
        """Grace-period sweep + retry of per-service erasure jobs (never dies on an error)."""
        while True:
            await asyncio.sleep(settings.deletion_worker_interval_seconds)
            try:
                await privacy.process_due(app)
            except Exception:
                log.exception("deletion worker tick failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await create_tables(engine)
        worker = asyncio.create_task(deletion_worker()) if settings.deletion_worker_interval_seconds > 0 else None
        yield
        if worker:
            worker.cancel()
        await http.aclose()
        await engine.dispose()

    app = FastAPI(title="Factory Finder gateway", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.clock = clock
    app.state.ws_tickets = WsTicketStore(clock, settings.ws_ticket_ttl_seconds, settings.ws_ticket_max)
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.http = http
    app.state.tokens = TokenService(
        settings.resolved_secret(), clock, settings.access_ttl_seconds, settings.refresh_ttl_seconds, settings.jwt_algorithm
    )  # fmt: skip
    app.state.home_client = home_client or (
        MockHomeClient()
        if settings.home_client == "mock"
        else HttpHomeClient(http, settings.upstream_map())
    )
    limiter = build_limit_store(
        clock, settings.rate_limit_max_keys, settings.redis_url, redis_client
    )
    app.state.limiter = limiter
    app.state.mailer = mailer or build_mailer(settings)
    if settings.require_email_verified and not app.state.mailer.enabled:
        log.warning("FF_GATEWAY_REQUIRE_EMAIL_VERIFIED is on but mail is off: nobody can verify")
    trusted_nets = settings.trusted_proxy_networks()  # fails at startup on a bad CIDR
    app.state.engine = engine
    write_methods = {"POST", "PUT", "PATCH", "DELETE"}

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
            media_read = request.method == "GET" and path.startswith(("/v1/media/files/", "/v1/media/private/"))
            limit = (
                settings.auth_rate_limit_per_minute
                if auth_route
                else settings.media_rate_limit_per_minute
                if media_read
                else settings.rate_limit_per_minute
            )
            peer = request.client.host if request.client else None
            ip = client_ip(peer, request.headers.get("x-forwarded-for"), trusted_nets)
            wait = await limiter.check(
                f"{'auth' if auth_route else 'media' if media_read else 'api'}:{ip}", limit
            )
            if wait is not None:
                e = RateLimited(wait, limit)
                return _error(e.status_code, e.code, e.message, e.details, e.headers)
            ulimit = settings.user_write_rate_limit_per_minute
            if ulimit > 0 and request.method in write_methods and not auth_route:
                uid = None
                if (tok := bearer_token(request)) is not None:
                    try:  # invalid tokens are left to the route (401); the IP limit already applied
                        uid = app.state.tokens.decode(tok, "access")
                    except Exception:
                        uid = None
                if uid:
                    wait = await limiter.check(f"user:{uid}", ulimit)
                    if wait is not None:
                        e = RateLimited(wait, ulimit)
                        return _error(e.status_code, e.code, e.message, e.details, e.headers)
            if path.startswith("/v1/admin"):  # admin-token guessing: throttle by failed attempts per IP
                fkey = f"adminfail:{ip}"
                if (wait := await limiter.blocked(fkey, 2 * settings.auth_rate_limit_per_minute)) is not None:
                    e = RateLimited(wait, settings.auth_rate_limit_per_minute)
                    return _error(e.status_code, e.code, e.message, e.details, e.headers)
                resp = await call_next(request)
                if resp.status_code == 401:
                    await limiter.check(fkey, 2 * settings.auth_rate_limit_per_minute)
                resp.headers["X-RateLimit-Limit"] = str(limit)
                return resp
            resp = await call_next(request)
            resp.headers["X-RateLimit-Limit"] = str(limit)  # remaining is not exposed: the store only reports blocked/allowed
            return resp
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME, "version": __version__}

    probe_cache: dict[str, object] = {"at": None, "result": {}}

    async def _probe(name: str, base: str) -> tuple[str, bool]:
        try:
            r = await http.get(base.rstrip("/") + "/health", timeout=2.0)
            return name, r.status_code == 200
        except Exception:
            return name, False

    @app.get("/ready")
    async def ready():
        db_ok = await db_ready(engine)
        now = clock.monotonic()
        at = probe_cache["at"]
        if at is None or now - at > 5.0:  # type: ignore[operator]  # cache: /ready is public
            results = await asyncio.gather(
                *(_probe(n, u) for n, u in settings.upstream_map().items())
            )
            probe_cache["result"], probe_cache["at"] = dict(results), now
        ups: dict[str, bool] = dict(probe_cache["result"])  # type: ignore[arg-type]
        resp = ready_response("gateway", {"database": db_ok})
        body = {**json.loads(resp.body), "upstreams": ups}
        if db_ok and not all(ups.values()):
            body["status"] = "degraded"
        return JSONResponse(body, status_code=resp.status_code)

    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(account.router)
    app.include_router(admin.router)
    app.include_router(admin_demand.router)
    app.include_router(admin_moderation.router)
    app.include_router(admin_payments.router)
    app.include_router(admin_media.router)
    app.include_router(admin_services.router)
    if settings.serve_admin:
        admin_dir = (
            Path(settings.admin_dir)
            if settings.admin_dir
            else Path(__file__).resolve().parents[4] / "apps" / "admin"
        )
        if (admin_dir / "index.html").is_file():
            app.mount("/admin", StaticFiles(directory=admin_dir, html=True), name="admin")
        else:
            log.warning("FF_GATEWAY_SERVE_ADMIN is set but %s/index.html was not found", admin_dir)
    app.include_router(ws.router)
    app.include_router(proxy.router)  # catch-all, must be last
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"],
        expose_headers=["X-Request-Id"], allow_credentials=False,
    )  # fmt: skip
    install_observability(app, "gateway", trust_user_header=False)  # outermost
    return app


app = create_app()
